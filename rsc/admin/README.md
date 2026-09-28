# Admin MixIn

This module is designed for RSC admins to perform day to day league management.

## Groups

- `/admin` - Main command group
    - `/admin members` - Manage members
    - `/admin franchise` - Manage franchises
    - `/admin permfa` - Poll Permanent Free Agents about converting to Free Agents
    - `/admin sync` - Sync data from API directly into discord server (**Caution**)

### Base Group Commands

- `/admin dates` - Configure the `/dates` command output

### Member Group

- `/admin members changename` - Change an RSC member name. Allows adding a new tracker.
- `/admin members create` - Create a new RSC member in API
- `/admin members delete` - Permanently delete an RSC member from our database
- `/admin members list` - List RSC members based on search criteria
- `/admin members notinserver` - Report current season league players who are no longer in the discord server. Read only; retire them with `/admin bulkretire`.

### Sync Group

- `/admin sync transactionchannels` - Check if all franchise transaction channels exist. If not, create them.
- `/admin sync franchiseroles` - Check if all franchise roles exist. If not, create them.
- `/admin sync tiers` - Create tier roles and associated channels
- `/admin sync requiredroles` - Create generic required roles for RSC

### Franchise Group

- `/admin franchise logo` - Upload a logo for a franchise
- `/admin franchise rebrand` - Rebrand a franchise
- `/admin franchise delete` - Delete a franchise
- `/admin franchise create` - Create a franchise
- `/admin franchise transfer` - Transfer ownership of a franchise to a new General Manager

### PermFA Group

Polls a tier's Permanent Free Agents by DM, asking whether they want to convert to a regular Free Agent. DMs go through the shared DM queue (`/admin dmstatus`). Each DM has Yes/No buttons that keep working across restarts, and players can change their answer until the poll closes 72 hours later. When a poll closes, the buttons are removed from every DM. Use `/admin permfa responses` to see the results. One poll is kept per tier, and starting a new one replaces the previous results.

- `/admin permfa poll` - DM every PermFA in a tier and open a 72 hour poll
- `/admin permfa dmtest` - Send a preview of the poll DM to a member, such as yourself. The buttons work, but nothing is recorded
- `/admin permfa responses` - Show answers for a tier's poll. Yes answers are listed first come, first served, with MMR
- `/admin permfa remind` - Re-DM PermFAs who have not answered. The original deadline still applies
- `/admin permfa close` - Close a tier's poll early
