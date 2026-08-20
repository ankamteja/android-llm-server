# Maintenance

Operational notes for running the phone as a headless server: what was pruned, and
how to manage packages without root or a screen.

## App cleanup (2026-08-21)

A stock phone ships a lot that a headless server never uses — nobody touches the
screen. 37 packages were removed with `pm uninstall --user 0 <pkg>`, which uninstalls
for the current user without root. It is reversible (`pm install-existing <pkg>`
restores the APK), but **app data is not kept** — so this was applied only to apps
holding no irreplaceable local state.

**Removed** (streaming, games, Samsung/carrier bloat, unused voice/translation packs,
junk utilities): Netflix, Prime Video, Hotstar, JioCinema, YT Music, Play Movies,
Google Earth, Play Games, Samsung Game Home, Samsung Free/Tips/Members/Shop, Kids Home,
AR Emoji, Expert RAW, Blackmagic Cam, Samsung remote support, APKMirror, CCleaner,
non-English Bixby + SMT + NMT language packs, a third-party find-my-device, Shazam,
UNiDAYS, Culture Circle, Pinterest Shuffles.

**Deliberately kept — do not remove blind:**

| Category | Why |
|---|---|
| Microsoft Authenticator | 2FA seeds; removing it can lock you out of accounts |
| Banking / UPI (PhonePe, Groww, GPay, Samsung Pay, …) | financial state + credentials |
| Messengers (WhatsApp, Telegram, Signal, Discord) | local chat history |
| VPN clients (Proton, OpenVPN, Pawxy, Freedom) | in use for connectivity experiments |
| **English Bixby + `SMT.lang_en_in`** | the dead-screen emergency access path is voice: "Hi Bixby → TalkBack", which needs on-device English TTS |
| Termux / Termux:Boot | the server itself |

## Managing packages headless

```sh
adb shell pm list packages -3            # third-party (user-installed)
adb shell pm list packages -d            # currently disabled
adb shell pm uninstall --user 0 <pkg>    # remove for this user (reversible)
adb shell pm install-existing <pkg>      # restore a removed system app
adb shell pm disable-user --user 0 <pkg> # disable without removing
```

`pm uninstall --user 0` is the safe primitive on an unrooted phone: it does not delete
the system image, only the current user's copy, so a factory-reset or `install-existing`
brings anything back.

## Battery

`protect_battery=1` is enabled, capping charge at ~85%. Combined with permanent USB
power, this keeps the cell from sitting at 100%/heat 24/7 and is the right setting for
an always-plugged server. Battery temperature idles ~31 °C under the LLM load measured.
