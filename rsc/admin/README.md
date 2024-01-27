# Admin MixIn

This module is designed for RSC admins to perform day to day league management.

## Groups

- `/admin` - Main command group
    - `/admin members` - Manage members
    - `/admin franchise` - Manage franchises
    - `/admin sync` - Sync data from API directly into discord server (**Caution**)

### Base Group Commands

- `/admin dates` - Configure the `/dates` command output

### Member Group

- `/admin members changename` - Change an RSC member name. Allows adding a new tracker.
- `/admin members create` - Create a new RSC member in API
- `/admin members delete` - Permanently delete an RSC member from our database
- `/admin members list` - List RSC members based on search criteria

### Sync Group

- `/admin sync transactionchannels` - Check if all franchise transaction channels exist. If not, create them.
- `/admin sync franchiseroles` - Check if all franchise roles exist. If not, create them.

### Franchise Group

- `/admin franchise logo` - Upload a logo for a franchise
- `/admin franchise rebrand` - Rebrand a franchise
- `/admin franchise delete` - Delete a franchise
- `/admin franchise create` - Create a franchise
- `/admin franchise transfer` - Transfer ownership of a franchise to a new General Manager
