#!/bin/bash

tar -czvf $HOME/backup/rsc_bot_backup.tar.gz $HOME/.local/share/Red-DiscordBot
gcloud storage rm gs://rsc-storage-bucket/rsc_bot_backup.tar.gz
gcloud storage cp $HOME/backup/rsc_bot_backup.tar.gz gs://rsc-storage-bucket/rsc_bot_backup.tar.gz
