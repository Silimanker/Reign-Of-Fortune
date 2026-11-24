from django.urls import path

from . import views

app_name = "game"

urlpatterns = [
    path("",                    views.splash,        name="splash"),
    path("menu/",               views.menu,          name="menu"),
    path("topup/",              views.topup,         name="topup"),
    path("topup/submit/",       views.topup_submit,  name="topup_submit"),
    path("ring/",               views.spatial_ring,  name="ring"),
    path("ring/cashout/",       views.cashout_submit, name="cashout_submit"),
    path("play/",               views.modes,         name="modes"),
    path("play/<slug:slug>/",   views.slot_screen,   name="slot"),
    path("paytable/",           views.paytable,      name="paytable"),
    path("api/spin/",           views.spin,          name="spin"),
    path("api/reset/",          views.reset_demo,    name="reset"),
]
