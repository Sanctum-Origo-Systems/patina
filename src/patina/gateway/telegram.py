from __future__ import annotations

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from patina.gateway.base import GatewayAdapter, InboundMessage


class TelegramAdapter(GatewayAdapter):
    def __init__(
        self,
        token: str,
        agent_url: str = "http://127.0.0.1:8321",
        allowed_users: list[int] | None = None,
    ) -> None:
        super().__init__(agent_url)
        self.token = token
        self.allowed_users = allowed_users
        self._app: Application | None = None

    async def start(self) -> None:
        self._app = Application.builder().token(self.token).build()
        self._app.add_handler(CommandHandler("start", self._handle_start))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()

    async def stop(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    async def _handle_start(self, update: Update, context) -> None:
        await update.message.reply_text("Connected. Send me a message.")

    async def _handle_message(self, update: Update, context) -> None:
        user_id = update.effective_user.id

        if self.allowed_users and user_id not in self.allowed_users:
            await update.message.reply_text("Not authorized.")
            return

        await update.effective_chat.send_action("typing")

        inbound = InboundMessage(
            channel=f"telegram-{user_id}",
            user_id=str(user_id),
            text=update.message.text,
            timestamp=update.message.date.timestamp(),
            platform="telegram",
        )

        try:
            response = await self.send_to_agent(inbound)
            await update.message.reply_text(response)
        except Exception as e:
            await update.message.reply_text(f"Error: {str(e)[:100]}")
