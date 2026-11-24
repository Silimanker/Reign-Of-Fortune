from django.contrib import admin

from .models import GameRound, Player, Transaction


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("name", "spirit_stones", "fortune_favor", "charm_active", "free_spins", "updated_at")


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "player", "kind", "amount", "balance_after", "status")
    list_filter = ("kind", "status")


@admin.register(GameRound)
class GameRoundAdmin(admin.ModelAdmin):
    list_display = ("created_at", "mode_name", "selection_label", "stake",
                    "multiplier", "payout", "cascade_count", "free_spins_won",
                    "result_key", "is_win", "is_free")
    list_filter = ("mode_slug", "bet_type", "is_win")
