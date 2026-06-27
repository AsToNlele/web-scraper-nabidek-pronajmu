import logging

import discord


class DiscordLogger(logging.Handler):
    def __init__(self, client, channel, level) -> None:
        super().__init__(level)
        self.client = client
        self.channel = channel

    def emit(self, record: logging.LogRecord):
        message = "**{}**\n```\n{}\n```".format(record.levelname, record.getMessage())

        task = self.client.loop.create_task(self._send(message))
        task.add_done_callback(self._handle_send_result)

    async def _send(self, message: str):
        if self.channel is None:
            return

        try:
            await self.channel.send(message)
        except discord.errors.HTTPException:
            pass

    def _handle_send_result(self, task):
        try:
            task.result()
        except Exception:
            pass
