class BettingGameCog:
    async def prepare_bet_round(self, betting_view, interaction, insufficient_message):
        balance = betting_view.get_balance()
        if betting_view.bet > balance:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        insufficient_message.format(balance=balance, bet=betting_view.bet),
                        ephemeral=True
                    )
            except Exception as error:
                print(f"[{self.__class__.__name__}] Error sending insufficient funds message: {error}")
            return False

        if betting_view.currency_name == "credits":
            self.economy.add_credits(betting_view.user.id, -betting_view.bet)
        else:
            self.economy.add_money(betting_view.user.id, -betting_view.bet)

        await betting_view.refresh_bet_message()

        if betting_view.game_message:
            try:
                await betting_view.game_message.delete()
            except Exception:
                pass
        return True
