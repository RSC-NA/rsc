# RSC Bot

RSCBot is a discored Cog written in Python that can be installed and used with the [Red Discord Bot](https://docs.discord.red/en/stable/index.html).

This was designed for use within [RSC (Rocket Soccar Confederation)](https://www.rocketsoccarconfederation.com/), a Rocket League Amateur League that has leagues operating in NA, EU, and SSA.

- [RSC NA 3v3 Discord](https://discord.gg/rsc)
- [RSC NA 2v2 Discord](https://discord.gg/se6NwxKjpZ)
- [RSC EU 3v3 Discord](https://discord.gg/Bw4rvpG)
- [RSC SSA 3v3 Discord](https://discord.gg/h2ynTF4mNJ)

## Installation

Follow the Red Discord Bot installation guide for [Windows](https://docs.discord.red/en/stable/install_windows.html) or [Linux/Mac](https://docs.discord.red/en/stable/install_linux_mac.html). You'll need to also [create a Discord bot account](https://discordpy.readthedocs.io/en/latest/discord.html) to get a token for use during the bot setup. After you have the bot setup, running, and invited to one of your Discord servers, you can begin installing and loading the cogs to the bot using the following commands in Discord (where `<p>` represents the prefix you selected your bot to use):

```
<p>load downloader
<p>repo add RSCBot https://github.com/RSC-NA/rsc.git [branch]
<p>cog install RSCBot rsc 
<p>load rsc 
```

## Configuration

After installation, you will need to configure some core values for each RSC discord. You can do this after inviting the bot to your RSC server and using the following commands.

- `/rsc key` - Set the RSC API key
- `/rsc url` - Set the RSC API url
- `/rsc league` - Select the league that correlates to the discord server

### Other Module Settings

There are a variety of settings available in a large number of modules for the bot. Please see the following for options.

- `/ballchasing` - Ballchasing Replay Settings
- `/combines` - Combine Settings
- `/moderation` - Mod Settings
- `/transactions` - Transactions Setings

