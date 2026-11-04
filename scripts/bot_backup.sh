#!/bin/bash
# Red's instance registry, config.json, lives outside the data directory, and Red
# cannot find an instance's data without it.
archive="$HOME/backup/rsc_bot_backup.tar.gz"

tar -czvf "$archive" "$HOME/.local/share/Red-DiscordBot" "$HOME/.config/Red-DiscordBot"
# GNU tar exits 1 when a file, such as a log, changed while it was read. That archive is still usable.
if [ $? -gt 1 ]; then
    echo "tar failed, keeping the previous backup in the bucket" >&2
    exit 1
fi

gcloud storage cp "$archive" gs://rsc-storage-bucket/rsc_bot_backup.tar.gz
