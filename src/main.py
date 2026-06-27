#!/usr/bin/evn python3
import asyncio
import logging
from datetime import datetime
from time import time

import discord
from discord.ext import tasks

from config import *
from discord_logger import DiscordLogger
from offers_filter import OfferFilter
from offers_storage import OffersStorage
from scrapers.rental_offer import RentalOffer
from scrapers_manager import create_scrapers, fetch_latest_offers


def get_current_daytime() -> bool: return datetime.now().hour in range(6, 22)


client = discord.Client(intents=discord.Intents.default())
daytime = get_current_daytime()
interval_time = config.refresh_interval_daytime_minutes if daytime else config.refresh_interval_nighttime_minutes
KEEP_REACTION = "✅"
REMOVE_REACTION = "❌"

scrapers = create_scrapers(config.dispositions)
offer_filter = OfferFilter(
    price_min=config.price_min,
    price_max=config.price_max,
    required_localities=config.required_localities,
    excluded_localities=config.excluded_localities
)


def discord_enabled() -> bool:
    return not config.debug or config.force_discord


def should_publish_offers(first_time: bool) -> bool:
    return discord_enabled() and (not first_time or config.force_discord)


def format_price(offer: RentalOffer) -> str:
    if (
        offer.total_price is not None
        and offer.rent_price is not None
        and offer.fees_price is not None
        and offer.fees_price > 0
    ):
        return f"{offer.total_price} Kč ({offer.rent_price} Kč nájem + {offer.fees_price} Kč poplatky)"

    if offer.total_price is not None:
        return f"{offer.total_price} Kč"

    return f"{offer.price} Kč"


def reaction_action(emoji: str) -> str | None:
    if emoji == KEEP_REACTION:
        return "save"
    if emoji == REMOVE_REACTION:
        return "delete"
    return None


def should_handle_reaction(user_id: int, bot_user_id: int | None, channel_id: int, emoji: str) -> bool:
    if bot_user_id is not None and user_id == bot_user_id:
        return False
    if channel_id != config.discord.offers_channel:
        return False
    return reaction_action(emoji) is not None


@client.event
async def on_ready():
    global channel, storage

    dev_channel = client.get_channel(config.discord.dev_channel)
    channel = client.get_channel(config.discord.offers_channel)
    storage = OffersStorage(config.found_offers_file)

    if discord_enabled():
        discord_error_logger = DiscordLogger(client, dev_channel, logging.ERROR)
        logging.getLogger().addHandler(discord_error_logger)
    else:
        logging.info("Discord logger is inactive in debug mode")

    logging.info("Available scrapers: " + ", ".join([s.name for s in scrapers]))
    logging.info(
        "Effective config: debug=%s force_discord=%s update_channel_topic=%s price_min=%s price_max=%s required_localities=%s excluded_localities=%s found_offers_file=%s offers_channel=%s saved_channel=%s dev_channel=%s",
        config.debug,
        config.force_discord,
        config.update_channel_topic,
        config.price_min,
        config.price_max,
        config.required_localities,
        config.excluded_localities,
        config.found_offers_file,
        config.discord.offers_channel,
        config.discord.saved_channel,
        config.discord.dev_channel
    )

    logging.info("Fetching latest offers every {} minutes".format(interval_time))

    process_latest_offers.start()

@tasks.loop(minutes=interval_time)
async def process_latest_offers():
    logging.info("Fetching offers")

    new_offers: list[RentalOffer] = []
    for offer in fetch_latest_offers(scrapers):
        if not storage.contains(offer):
            new_offers.append(offer)

    first_time = storage.first_time

    logging.info("Offers fetched (new: {})".format(len(new_offers)))
    filtered_offers, rejected_offers = offer_filter.filter(new_offers)
    logging.info("Offers after filtering: %s accepted, %s rejected", len(filtered_offers), len(rejected_offers))

    if config.debug and not config.force_discord:
        logging.info("Debug mode is active, skipping Discord publishing")
        storage.save_offers(new_offers)
    elif should_publish_offers(first_time):
        storage.save_offers(rejected_offers)

        if not filtered_offers:
            logging.info("No new offers to publish")

        for offer in filtered_offers:
            embed = discord.Embed(
                title=offer.title,
                url=offer.link,
                description=offer.location,
                timestamp=datetime.utcnow(),
                color=offer.scraper.color
            )
            embed.add_field(name="Cena", value=format_price(offer))
            embed.set_author(name=offer.scraper.name, icon_url=offer.scraper.logo_url)
            embed.set_image(url=offer.image_url)

            if not await retry_until_successful_send(channel, embed):
                logging.error("Publishing failed, leaving unsent offers out of storage for the next run")
                return

            storage.save_offers([offer])
            await asyncio.sleep(1.5)
    elif first_time:
        logging.info("No previous offers, first fetch is running silently")
        storage.save_offers(new_offers)

    global daytime, interval_time
    if daytime != get_current_daytime():  # Pokud stary daytime neodpovida novemu

        daytime = not daytime  # Zneguj daytime (podle podminky se zmenil)

        interval_time = config.refresh_interval_daytime_minutes if daytime else config.refresh_interval_nighttime_minutes

        logging.info("Fetching latest offers every {} minutes".format(interval_time))
        process_latest_offers.change_interval(minutes=interval_time)

    if discord_enabled() and config.update_channel_topic:
        await retry_until_successful_edit(channel, f"Last update <t:{int(time())}:R>")


@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    bot_user_id = client.user.id if client.user is not None else None
    if not should_handle_reaction(payload.user_id, bot_user_id, payload.channel_id, str(payload.emoji)):
        return

    action = reaction_action(str(payload.emoji))

    channel = await get_text_channel(payload.channel_id)
    if channel is None:
        logging.warning("Could not find Discord offers channel for reaction handling")
        return

    try:
        message = await channel.fetch_message(payload.message_id)
    except discord.errors.NotFound:
        logging.warning("Reacted Discord message %s no longer exists", payload.message_id)
        return

    if client.user is not None and message.author.id != client.user.id:
        return

    if action == "save":
        await repost_to_saved_channel(message)
    elif action == "delete":
        await delete_offer_message(message)


async def get_text_channel(channel_id: int):
    channel = client.get_channel(channel_id)
    if channel is not None:
        return channel

    try:
        return await client.fetch_channel(channel_id)
    except discord.errors.HTTPException as e:
        logging.warning("Could not fetch Discord channel %s: %s", channel_id, e)
        return None


async def repost_to_saved_channel(message: discord.Message):
    saved_channel = await get_text_channel(config.discord.saved_channel)
    if saved_channel is None:
        logging.warning("Could not find Discord saved channel")
        return

    try:
        if message.embeds:
            await saved_channel.send(embeds=message.embeds)
        elif message.content:
            await saved_channel.send(message.content)
        else:
            await saved_channel.send(message.jump_url)
        logging.info("Offer message %s reposted to saved channel", message.id)
    except discord.errors.HTTPException as e:
        logging.warning("Could not repost offer message %s: %s", message.id, e)


async def delete_offer_message(message: discord.Message):
    try:
        await message.delete()
        logging.info("Offer message %s deleted after user reaction", message.id)
    except discord.errors.HTTPException as e:
        logging.warning("Could not delete offer message %s: %s", message.id, e)


async def retry_until_successful_send(channel: discord.TextChannel, embed: discord.Embed, delay: float = 5.0) -> bool:
    """Retry sending a message with one embed until it succeeds."""
    while True:
        try:
            message = await channel.send(embed=embed)
            await add_offer_reactions(message)
            logging.info("Embed successfully sent.")
            return True
        except discord.errors.DiscordServerError as e:
            logging.warning(f"Discord server error while sending embed: {e}. Retrying in {delay:.1f}s.")
        except discord.errors.Forbidden as e:
            logging.error(f"Discord rejected sending embed because of missing permissions: {e}.")
            return False
        except discord.errors.HTTPException as e:
            logging.warning(f"HTTPException while sending embed: {e}. Retrying in {delay:.1f}s.")
        except Exception as e:
            logging.exception(f"Unexpected error while sending embed: {e}. Retrying in {delay:.1f}s.")
            raise e
        await asyncio.sleep(delay)


async def add_offer_reactions(message: discord.Message):
    for reaction in (KEEP_REACTION, REMOVE_REACTION):
        try:
            await message.add_reaction(reaction)
        except discord.errors.HTTPException as e:
            logging.warning("Could not add %s reaction to offer message %s: %s", reaction, message.id, e)


async def retry_until_successful_edit(channel: discord.TextChannel, topic: str, delay: float = 5.0):
    """Retry editing a channel topic until it succeeds."""
    while True:
        try:
            await channel.edit(topic=topic)
            logging.info(f"Channel topic successfully updated to: {topic}")
            return
        except discord.errors.DiscordServerError as e:
            logging.warning(f"Discord server error while editing topic: {e}. Retrying in {delay:.1f}s.")
        except discord.errors.Forbidden as e:
            logging.warning(f"Discord rejected editing the channel topic because of missing permissions: {e}.")
            return
        except discord.errors.HTTPException as e:
            logging.warning(f"HTTPException while editing topic: {e}. Retrying in {delay:.1f}s.")
        except Exception as e:
            logging.exception(f"Unexpected error while editing channel topic: {e}. Retrying in {delay:.1f}s.")
            raise e
        await asyncio.sleep(delay)

if __name__ == "__main__":
    logging.basicConfig(
        level=(logging.DEBUG if config.debug else logging.INFO),
        format='%(asctime)s - [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S')

    logging.debug("Running in debug mode")

    client.run(config.discord.token, log_level=logging.INFO)
