# Deprecated Ballchasing Functions

#     @_ballchasing.command(  # type: ignore[type-var]
#         name="reportall",
#         description="Find and report all matches for the day on ballchasing",
#     )
#     @app_commands.describe(
#         matchday="Match day to report (Optional: Defaults to current match day)",
#         matchtype="Match type to find. (Default: Regular Season)",
#         force="Force reporting even if match has been marked completed. (Default: False)",
#         upload="Enable or disable replay uploads to RSC ballchasing group. (Default: True)",
#         announce="Announce the match result to the tier score reporting channel. (Default: True)",
#     )
#     async def _bc_reportall(
#         self,
#         interaction: discord.Interaction,
#         matchday: int | None = None,
#         matchtype: MatchType = MatchType.REGULAR,
#         force: bool = False,
#         upload: bool = True,
#         announce: bool = True,
#     ):
#         guild = interaction.guild
#         if not (guild and isinstance(interaction.user, discord.Member)):
#             return

#         if not await self.has_bc_permissions(interaction.user):
#             await interaction.response.send_message(
#                 "You do not have permission to run this command.", ephemeral=True
#             )
#             return

#         log_channel = await self._get_bc_log_channel(guild)
#         if not log_channel:
#             await interaction.response.send_message(
#                 embed=ErrorEmbed(
#                     description="Ballchasing log channel is not configured."
#                 ),
#                 ephemeral=True,
#             )
#             return

#         # Send loading...
#         await interaction.response.send_message(
#             embed=BlueEmbed(
#                 title="Replay Processing Started",
#                 description="Please be patient while match data is collected...",
#             ),
#             ephemeral=True,
#         )

#         date_gt = None
#         date_lt = None
#         if not matchday:
#             log.debug("Match day not specified. Searching by todays date")
#             # Get guild timezone
#             tz = await self.timezone(guild)
#             date = datetime.now(tz=tz).replace(
#                 hour=0, minute=0, second=0, microsecond=0
#             )
#             date_gt, date_lt = await self.get_match_date_range(date)

#         # Get match by teams and date
#         log.debug(f"Fetching matches for {matchday or 'today'}. Type: {matchtype}")
#         mlist: list[MatchList] = await self.matches(
#             guild,
#             date__lt=date_lt,
#             date__gt=date_gt,
#             day=matchday,
#             match_type=matchtype,
#             # limit=40,  # Development limit. TODO FIX ME
#             limit=500,
#         )
#         log.debug(f"Found {len(mlist)} matches")

#         # No match found
#         if not mlist:
#             await interaction.followup.send(
#                 embed=ErrorEmbed(description="No matches found."), ephemeral=True
#             )
#             return

#         log.debug("Fetching detailed match data")
#         mtasks: list[asyncio.Task] = []
#         # Workaround for now
#         for i in range(0, len(mlist), LARGE_BATCH_SIZE):
#             log.debug(f"Fetching batch {i}")
#             mbatch = mlist[i : i + LARGE_BATCH_SIZE]
#             try:
#                 async with asyncio.TaskGroup() as tg:
#                     for m in mbatch:
#                         if m.id:
#                             mtasks.append(tg.create_task(self.match_by_id(guild, m.id)))
#             except ExceptionGroup as eg:
#                 for err in eg.exceptions:
#                     log.error(f"ExceptionGroup Err: {err}")
#                 raise eg
#         matches: list[Match] = [r.result() for r in mtasks]

#         log.debug("Fetching tier data")
#         tiers = await self.tiers(guild)
#         if not tiers:
#             await interaction.edit_original_response(
#                 embed=ErrorEmbed(description="Unable to fetch tier data.")
#             )

#         if not matches:
#             await interaction.edit_original_response(
#                 embed=ErrorEmbed(description="Unable to fetch detailed match data.")
#             )
#             return

#         stats_role = await self._get_bc_manager_role(guild)

#         # ballchasing match day groups
#         tgroups: dict[str, str | None] = {}
#         for match in matches:
#             if tgroups.get(match.home_team.tier):
#                 continue
#             grp = await self.match_day_bc_group(guild, match)
#             if grp:
#                 url = await self.bc_group_full_url(grp)
#                 tgroups[match.home_team.tier] = url

#         report_view = BallchasingProcessingView(
#             interaction, matches, tiers, log_channel, stats_role
#         )
#         report_view.tier_groups = tgroups
#         await report_view.prompt()

#         # Shuffle because it looks better :)
#         random.shuffle(matches)

#         log.debug("Fetching matches from ballchasing")
#         bc_results: list[BallchasingResult] = []
#         for i in range(0, len(matches), LARGE_BATCH_SIZE):
#             if report_view.cancelled:
#                 continue

#             log.debug(f"Fetching batch {i}")
#             bcbatch = matches[i : i + LARGE_BATCH_SIZE]

#             await report_view.next_batch(bcbatch)

#             # Discovery replays
#             task_results: list[BallchasingResult] = []
#             bc_tasks: list[asyncio.Task] = []
#             try:
#                 async with asyncio.TaskGroup() as tg:
#                     for b in bcbatch:
#                         bc_tasks.append(tg.create_task(self.process_match(guild, b)))
#             except ExceptionGroup as eg:
#                 for err in eg.exceptions:
#                     log.error(err)
#                 raise eg

#             # Store successful results
#             task_results = [r.result() for r in bc_tasks]

#             upload_tasks = []
#             if upload:
#                 # Upload to ballchasing
#                 log.debug("Uploading result batch to ballchasing")
#                 async with asyncio.TaskGroup() as tg:
#                     for result in task_results:
#                         utask = tg.create_task(
#                             self.create_and_upload_replays(guild, result)
#                         )
#                         upload_tasks.append(utask)
#                 upload_results = [u.result() for u in upload_tasks]

#                 for i in range(len(upload_results)):
#                     url = await self.bc_group_full_url(upload_results[i])
#                     task_results[i]["link"] = url

#             # Announce to score report channel
#             if announce:
#                 log.debug("Announcing result batch")
#                 embed_tasks = []
#                 async with asyncio.TaskGroup() as tg:
#                     for result in task_results:
#                         log.debug(f"Match Valid: {result['valid']}")
#                         log.debug(
#                             f"Home Wins {result['home_wins']} Away Wins: {result['away_wins']}"
#                         )
#                         if not result["valid"]:
#                             continue
#                         mtier = result["match"].home_team.tier
#                         etask = tg.create_task(
#                             self.build_match_result_embed(
#                                 guild, result=result, link=result["link"]
#                             )
#                         )
#                         embed_tasks.append(etask)

#                 embed_results = [e.result() for e in embed_tasks]

#                 log.debug(f"Embed Len: {len(embed_results)}")
#                 for i in range(len(embed_results)):
#                     mtier = task_results[i]["match"].home_team.tier
#                     await self.announce_to_score_reporting(
#                         guild, tier=mtier, embed=embed_results[i]
#                     )

#             bc_results.extend(task_results)
#             await report_view.update(
#                 [tr["match"] for tr in task_results if tr["valid"]]
#             )

#         await report_view.finished()
#         await report_view.prompt()

#         # Missing matches
#         for r in bc_results:
#             if not r["valid"]:
#                 rmatch = r["match"]
#                 log.debug(
#                     (
#                         f"{rmatch.home_team.name} vs {rmatch.away_team.name} not found."
#                         f" Total Replays: {len(r['replays'])}"
#                     )
#                 )

#         # Statistics
#         exc_times = [x["execution_time"] for x in bc_results]
#         median = statistics.median(exc_times)
#         fmean = statistics.fmean(exc_times)
#         stdev = statistics.stdev(exc_times)
#         log.debug(f"Median execution time: {median}")
#         log.debug(f"Mean execution time: {fmean}")
#         log.debug(f"Standard deviation: {stdev}")
#         for x in bc_results:
#             if x["execution_time"] > (median + 2 * stdev):
#                 match = x["match"]
#                 home = match.home_team.name
#                 away = match.away_team.name
#                 log.warning(
#                     f"Very slow execution time for {home} vs {away}. ExecutionTime={x['execution_time']}"
#                 )

#             # match_group = await self.rsc_match_bc_group(interaction.guild, match)
#             # if match_group:
#             #     await self.upload_replays(
#             #         guild=interaction.guild,
#             #         group=match_group,
#             #         match=match,
#             #         result=result,
#             #     )
#             # else:
#             #     log.error("Failed to retrieve or create a ballchasing group for match.")

#     @_ballchasing.command(  # type: ignore[type-var]
#         name="reporttier",
#         description="Report a specific tier on ballchasing",
#     )
#     @app_commands.autocomplete(tier=TierMixIn.tier_autocomplete)  # type: ignore[type-var]
#     @app_commands.describe(
#         tier="Tier name to report",
#         matchday="Match day to report (Optional: Defaults to current match day)",
#         matchtype="Match type to find. (Default: Regular Season)",
#         force="Force reporting even if match has been marked completed. (Default: False)",
#         upload="Enable or disable replay uploads to RSC ballchasing group. (Default: True)",
#         announce="Announce the match result to the tier score reporting channel. (Default: True)",
#     )
#     async def _bc_reporttier(
#         self,
#         interaction: discord.Interaction,
#         tier: str,
#         matchday: int | None = None,
#         matchtype: MatchType = MatchType.REGULAR,
#         force: bool = False,
#         upload: bool = True,
#         announce: bool = True,
#     ):
#         guild = interaction.guild
#         if not (guild and isinstance(interaction.user, discord.Member)):
#             return

#         if not await self.has_bc_permissions(interaction.user):
#             await interaction.response.send_message(
#                 "You do not have permission to run this command.", ephemeral=True
#             )
#             return

#         # Defer
#         await interaction.response.defer()

#         date_gt = None
#         date_lt = None
#         if not matchday:
#             log.debug("Match day not specified. Searching by todays date")
#             # Get guild timezone
#             tz = await self.timezone(guild)
#             date = datetime.now(tz=tz).replace(
#                 hour=0, minute=0, second=0, microsecond=0
#             )
#             date_gt, date_lt = await self.get_match_date_range(date)

#         # Get match by teams and date
#         log.debug(f"Fetching matches for {tier}. Type: {matchtype}")
#         mlist: list[MatchList] = await self.matches(
#             guild,
#             date__lt=date_lt,
#             date__gt=date_gt,
#             day=matchday,
#             match_type=matchtype,
#             limit=100,
#         )
#         log.debug("Done searching")

#         # No match found
#         if not mlist:
#             await interaction.followup.send(
#                 embed=ErrorEmbed(description="No matches found.")
#             )
#             return
#         # TODO need monty to add tier search

#     @_ballchasing.command(  # type: ignore[type-var]
#         name="reportmatch",
#         description="Report a specific match on ballchasing",
#     )
#     @app_commands.autocomplete(
#         home=TeamMixIn.teams_autocomplete,
#         away=TeamMixIn.teams_autocomplete,
#     )  # type: ignore[type-var]
#     @app_commands.describe(
#         home="Home team name",
#         away="Away team name",
#         date='Match date in ISO 8601 format. Defaults to todays date. (Example: "2023-01-25")',
#         force="Force reporting even if match has been marked completed. (Default: False)",
#         upload="Enable or disable replay uploads to RSC ballchasing group. (Default: True)",
#         announce="Announce the match result to the tier score reporting channel. (Default: True)",
#     )
#     async def _bc_reportmatch_cmd(
#         self,
#         interaction: discord.Interaction,
#         home: str,
#         away: str,
#         date: Transform[datetime, DateTransformer] | None = None,
#         force: bool = False,
#         upload: bool = True,
#         announce: bool = True,
#     ):
#         if not (interaction.guild and isinstance(interaction.user, discord.Member)):
#             return

#         if not await self.has_bc_permissions(interaction.user):
#             await interaction.response.send_message(
#                 "You do not have permission to run this command.", ephemeral=True
#             )
#             return

#         # Defer
#         await interaction.response.defer()

#         # Get guild timezone
#         tz = await self.timezone(interaction.guild)

#         # Add timezone to date. If date not supplied, use todays date()
#         if date:
#             date = date.replace(tzinfo=tz)
#         else:
#             date = datetime.now(tz=tz).replace(
#                 hour=0, minute=0, second=0, microsecond=0
#             )

#         # date = datetime(2023, 9, 11, tzinfo=tz)  # TEST REMOVE ME
#         log.info(
#             f"Searching for individual match. Home: {home} Away: {away} Date: {date}"
#         )

#         # Get match by teams and date
#         date_gt, date_lt = await self.get_match_date_range(date)
#         log.debug(f"Search Start: {date_gt} Search End: {date_lt}")
#         matches: list[Match] = await self.find_match(
#             interaction.guild,
#             date__lt=date_lt,
#             date__gt=date_gt,
#             teams=f"{home}, {away}",
#             limit=1,
#         )
#         log.debug("Done searching")

#         # No match found
#         if not matches:
#             await interaction.followup.send(
#                 embed=ErrorEmbed(
#                     description="No matches found for specified teams and date."
#                 )
#             )
#             return

#         match = None
#         for m in matches:
#             if m.home_team.name == home and m.away_team.name == away:
#                 match = m

#         if not match:
#             await interaction.followup.send(
#                 embed=ErrorEmbed(
#                     description=(
#                         f"Unable to find match for **{home}** vs **{away}**."
#                         " Try specifying a date."
#                     )
#                 )
#             )
#             return

#         log.debug("Match found in RSC API.")

#         # Check if match is already complete
#         if await self.match_already_complete(match) and not force:
#             await interaction.followup.send(
#                 embed=ErrorEmbed(
#                     description=(
#                         "This match has already been completed and recorded."
#                         "\n\nRun the command again with `force` parameter to pull regardless."
#                     )
#                 )
#             )
#             return

#         # Check if team name matches
#         if not await self.check_team_type_match(home, away, match):
#             log.debug("Team names do not match home/away")
#             await interaction.followup.send(
#                 embed=ErrorEmbed(
#                     description="Home or away team name is not correct for the match found."
#                 )
#             )
#             return

#         # log.debug("Team names match home/away")

#         log.debug(f"Match ID: {match.id}")

#         if not match.var_date:
#             return await interaction.followup.send(
#                 embed=ErrorEmbed(
#                     description="Match API data is missing a date. Please open a modmail ticket.",
#                 )
#             )

#         # Send "working" message
#         await interaction.followup.send(
#             embed=YellowEmbed(
#                 title="Processing Match",
#                 description=f"Searching ballchasing for match **{home}** vs **{away}** on **{match.var_date.date()}**",
#             )
#         )

#         result = await self.process_match(interaction.guild, match)

#         if not result or not result["valid"]:
#             fembed = RedEmbed(
#                 title="Match Processing Failed",
#                 description="Unable to find a valid replay set.",
#             )
#             if match.var_date:
#                 fembed.add_field(
#                     name="Date",
#                     value=discord.utils.format_dt(match.var_date),
#                     inline=True,
#                 )
#             fembed.add_field(name="Home", value=home, inline=True)
#             fembed.add_field(name="Away", value=away, inline=True)
#             await interaction.edit_original_response(embed=fembed)
#             return

#         match_group = None
#         tier = match.home_team.tier
#         embed = await self.build_match_result_embed(
#             guild=interaction.guild, result=result, link=None
#         )  # TODO give link

#         # Give notice that replays are not being uploaded
#         if not upload:
#             embed.set_footer(text="Replays were NOT uploaded to ballchasing.")
#         else:
#             match_group = await self.rsc_match_bc_group(interaction.guild, match)
#             if match_group:
#                 await self.upload_replays(
#                     guild=interaction.guild,
#                     group=match_group,
#                     result=result,
#                 )
#             else:
#                 log.error("Failed to retrieve or create a ballchasing group for match.")

#         if match_group:
#             url = await self.bc_group_full_url(match_group)
#             embed.url = url

#         if announce:
#             await self.announce_to_score_reporting(
#                 guild=interaction.guild, tier=tier, embed=embed
#             )

#         await interaction.edit_original_response(embed=embed)

#    @_ballchasing.command(  # type: ignore[type-var]
#         name="reportmatch",
#         description="Report a specific match on ballchasing",
#     )
#     @app_commands.autocomplete(
#         home=TeamMixIn.teams_autocomplete,
#         away=TeamMixIn.teams_autocomplete,
#     )  # type: ignore[type-var]
#     @app_commands.describe(
#         home="Home team name",
#         away="Away team name",
#         date='Match date in ISO 8601 format. Defaults to todays date. (Example: "2023-01-25")',
#         force="Force reporting even if match has been marked completed. (Default: False)",
#         upload="Enable or disable replay uploads to RSC ballchasing group. (Default: True)",
#         announce="Announce the match result to the tier score reporting channel. (Default: True)",
#     )
#     async def _bc_report(
#         self,
#         interaction: discord.Interaction,
#         home: str,
#         away: str,
#         date: Transform[datetime, DateTransformer] | None = None,
#         force: bool = False,
#         upload: bool = True,
#         announce: bool = True,
#     ):
#         if not (interaction.guild and isinstance(interaction.user, discord.Member)):
#             return

#         if not await self.has_bc_permissions(interaction.user):
#             await interaction.response.send_message(
#                 "You do not have permission to run this command.", ephemeral=True
#             )
#             return

#         # Defer
#         await interaction.response.defer()

#         # Get guild timezone
#         tz = await self.timezone(interaction.guild)

#         # Add timezone to date. If date not supplied, use todays date()
#         if date:
#             date = date.replace(tzinfo=tz)
#         else:
#             date = datetime.now(tz=tz).replace(
#                 hour=0, minute=0, second=0, microsecond=0
#             )

#         # date = datetime(2023, 9, 11, tzinfo=tz)  # TEST REMOVE ME
#         log.info(
#             f"Searching for individual match. Home: {home} Away: {away} Date: {date}"
#         )

#         # Get match by teams and date
#         date_gt, date_lt = await self.get_match_date_range(date)
#         log.debug(f"Search Start: {date_gt} Search End: {date_lt}")
#         matches: list[Match] = await self.find_match(
#             interaction.guild,
#             date__lt=date_lt,
#             date__gt=date_gt,
#             teams=f"{home}, {away}",
#             limit=1,
#         )
#         log.debug("Done searching")

#         # No match found
#         if not matches:
#             await interaction.followup.send(
#                 embed=ErrorEmbed(
#                     description="No matches found for specified teams and date."
#                 )
#             )
#             return

#         match = None
#         for m in matches:
#             if m.home_team.name == home and m.away_team.name == away:
#                 match = m

#         if not match:
#             await interaction.followup.send(
#                 embed=ErrorEmbed(
#                     description=(
#                         f"Unable to find match for **{home}** vs **{away}**."
#                         " Try specifying a date."
#                     )
#                 )
#             )
#             return

#         log.debug("Match found in RSC API.")

#         # Check if match is already complete
#         if await self.match_already_complete(match) and not force:
#             await interaction.followup.send(
#                 embed=ErrorEmbed(
#                     description=(
#                         "This match has already been completed and recorded."
#                         "\n\nRun the command again with `force` parameter to pull regardless."
#                     )
#                 )
#             )
#             return

#         # Check if team name matches
#         if not await self.check_team_type_match(home, away, match):
#             log.debug("Team names do not match home/away")
#             await interaction.followup.send(
#                 embed=ErrorEmbed(
#                     description="Home or away team name is not correct for the match found."
#                 )
#             )
#             return

#         # log.debug("Team names match home/away")

#         log.debug(f"Match ID: {match.id}")

#         if not match.var_date:
#             return await interaction.followup.send(
#                 embed=ErrorEmbed(
#                     description="Match API data is missing a date. Please open a modmail ticket.",
#                 )
#             )

#         # Send "working" message
#         await interaction.followup.send(
#             embed=YellowEmbed(
#                 title="Processing Match",
#                 description=f"Searching ballchasing for match **{home}** vs **{away}** on **{match.var_date.date()}**",
#             )
#         )

#         result = await self.process_match(interaction.guild, match)

#         if not result or not result["valid"]:
#             fembed = RedEmbed(
#                 title="Match Processing Failed",
#                 description="Unable to find a valid replay set.",
#             )
#             if match.var_date:
#                 fembed.add_field(
#                     name="Date",
#                     value=discord.utils.format_dt(match.var_date),
#                     inline=True,
#                 )
#             fembed.add_field(name="Home", value=home, inline=True)
#             fembed.add_field(name="Away", value=away, inline=True)
#             await interaction.edit_original_response(embed=fembed)
#             return

#         match_group = None
#         tier = match.home_team.tier
#         embed = await self.build_match_result_embed(
#             guild=interaction.guild, result=result, link=None
#         )  # TODO give link

#         # Give notice that replays are not being uploaded
#         if not upload:
#             embed.set_footer(text="Replays were NOT uploaded to ballchasing.")
#         else:
#             match_group = await self.rsc_match_bc_group(interaction.guild, match)
#             if match_group:
#                 await self.upload_replays(
#                     guild=interaction.guild,
#                     group=match_group,
#                     result=result,
#                 )
#             else:
#                 log.error("Failed to retrieve or create a ballchasing group for match.")

#         if match_group:
#             url = await self.bc_group_full_url(match_group)
#             embed.url = url

#         if announce:
#             await self.announce_to_score_reporting(
#                 guild=interaction.guild, tier=tier, embed=embed
#             )

#         await interaction.edit_original_response(embed=embed)

# async def process_match(
#     self, guild: discord.Guild, match: Match, replays=list[discord.Attachment]
# ) -> BallchasingResult:
#     log.debug(
#         f"Searching ballchasing for {match.home_team.name} vs {match.away_team.name}"
#     )

#     st = time.time()

#     result = BallchasingResult(
#         valid=False,
#         match=match,
#         home_wins=0,
#         away_wins=0,
#         replays=set(),
#         execution_time=0,
#         link=None,
#     )

#     # Get trackers
#     log.debug("Fetching trackers")
#     trackers = await self.get_all_trackers(guild, match)
#     log.debug(f"Found {len(trackers)} trackers")

#     replays = set()
#     steam_trackers = [t for t in trackers if t.platform == "STEAM"]
#     other_trackers = [t for t in trackers if t.platform != "STEAM"]

#     min_games = await validation.minimum_games_required(match)
#     log.debug(f"Minimum match games required for upload: {min_games}")

#     # Check steam first, provides better results by uploader search.
#     log.debug("Finding games from STEAM trackers")
#     for acc in steam_trackers:
#         found = await self.find_match_replays(guild, match, acc)
#         replays.update(found)
#         if len(replays) >= min_games:
#             break

#     # Search other trackers if set not found
#     if not replays or len(replays) < 4:
#         log.debug("Valid replay set not found. Checking other trackers.")
#         for acc in other_trackers:
#             found = await self.find_match_replays(guild, match, acc)
#             replays.update(found)
#             if len(replays) >= min_games:
#                 break

#     # Second chance check for valid replay set
#     if len(replays) != min_games:
#         log.warning(
#             f"[{match.home_team.name} vs {match.away_team.name}] Found {len(replays)} replays but expected {min_games}"
#         )
#     else:
#         log.debug(f"Found valid set of {len(replays)} replays")
#         result["valid"] = True

#     et = time.time()
#     exc_time = et - st

#     hwins, awins = await self.team_win_count(match, replays)

#     result["execution_time"] = exc_time
#     result["home_wins"] = hwins
#     result["away_wins"] = awins
#     result["replays"] = replays
#     return result


# async def group_replay_collisions(
#     self, guild: discord.Guild, group: str, result: BallchasingResult
# ) -> BallchasingCollisions:
#     collisions = set()
#     unknown = set()
#     total_replays = 0
#     bapi = self._ballchasing_api.get(guild.id)

#     if not bapi:
#         raise RuntimeError("Ballchasing API is not configured.")

#     async for replay in bapi.get_group_replays(
#         group_id=group, deep=True, recurse=False
#     ):
#         total_replays += 1
#         if replay in result["replays"]:
#             collisions.add(replay)
#         else:
#             unknown.add(replay)

#     return BallchasingCollisions(
#         total_replays=total_replays,
#         unknown=unknown,
#         collisions=collisions,
#     )


# async def upload_replays(
#     self, guild: discord.Guild, group: str, result: BallchasingResult
# ) -> list[str]:
#     bapi = self._ballchasing_api.get(guild.id)
#     if not bapi:
#         raise RuntimeError("Ballchasing API is not configured.")

#     if not result["replays"]:
#         return []

#     match = result["match"]

#     collisions = await self.group_replay_collisions(guild, group, result)
#     if not collisions:
#         return []

#     total_collisions = len(collisions["collisions"])
#     total_unknown = len(collisions["unknown"])
#     total_replays = collisions["total_replays"]

#     log.debug(
#         f"Collision Report. Total={total_replays} Unknown={total_unknown} Collisions={total_collisions}"
#     )
#     min_games = await validation.minimum_games_required(match)

#     if total_collisions == min_games:
#         # Match already uploaded
#         log.debug("Match already uploaded. Skipping...")
#         return [r.id for r in result["replays"]]
#     elif total_unknown > 0:
#         # To save on complexity, purge the group if an unknown match_guid is found
#         log.warning("Unknown group replay found. Purging group...")
#         await groups.purge_ballchasing_group(guild, group)
#     elif total_collisions > 0:
#         # Remove collisions from upload list
#         for replay in collisions["collisions"]:
#             log.debug(f"Removing replay collision: {replay.id}")
#             result["replays"].remove(replay)

#     replay_content = []
#     for replay in result["replays"]:
#         data = await bapi.download_replay_content(replay.id)
#         if data:
#             replay_content.append(data)

#     replay_ids = []
#     for rbytes in replay_content:
#         rname = f"{''.join(random.choices(string.ascii_letters + string.digits, k=64))}.replay"
#         try:
#             resp = await bapi.upload_replay_from_bytes(
#                 name=rname,
#                 replay_data=rbytes,
#                 visibility=ballchasing.Visibility.PUBLIC,
#                 group=group,
#             )
#             if resp:
#                 replay_ids.append(resp.id)
#         except ValueError as exc:
#             log.debug(exc)
#             err = exc.args[0]
#             if err.status == 409:
#                 # duplicate replay. patch it under the BC group
#                 err_info = await err.json()
#                 log.debug(f"Error uploading replay. {err.status} -- {err_info}")
#                 r_id = err_info.get("id")
#                 if r_id:
#                     log.debug("Patching replay under correct group")
#                     await bapi.patch_replay(r_id, group=group)
#                     replay_ids.append(r_id)
#     return replay_ids

#    async def find_match_replays(
#         self, guild: discord.Guild, match: Match, tracker: TrackerLink
#     ) -> set[ballchasing.models.Replay]:
#         after, before = await self.get_bc_date_range(match)
#         log.debug(f"Ballchasing Date Range. After: {after} Before: {before}")
#         bapi = self._ballchasing_api[guild.id]

#         replays: set[ballchasing.models.Replay] = set()
#         min_games = await validation.minimum_games_required(match)

#         if tracker.platform == "STEAM":
#             log.debug(f"Searching tracker: {tracker.platform_id}")
#             async for r in bapi.get_replays(
#                 playlist=[ballchasing.Playlist.PRIVATE],
#                 sort_by=ballchasing.ReplaySortBy.REPLAY_DATE,
#                 sort_dir=ballchasing.SortDir.ASCENDING,
#                 replay_after=after,
#                 replay_before=before,
#                 uploader=tracker.platform_id,
#                 deep=True,
#             ):
#                 if await self.valid_replay(match, r):
#                     log.debug(f"Found Match: {r.id}")
#                     replays.add(r)

#                 if len(replays) == min_games:
#                     break
#         else:
#             if not tracker.name:
#                 return replays

#             log.debug(f"Searching {tracker.platform} tracker: {tracker.name}")
#             async for r in bapi.get_replays(
#                 playlist=[ballchasing.Playlist.PRIVATE],
#                 sort_by=ballchasing.ReplaySortBy.REPLAY_DATE,
#                 sort_dir=ballchasing.SortDir.ASCENDING,
#                 replay_after=after,
#                 replay_before=before,
#                 player_name=[tracker.name],
#                 deep=True,
#             ):
#                 if await self.valid_replay(match, r):
#                     log.debug(f"Found Match: {r.id}")
#                     # Avoid duplicate match_guids
#                     if r in replays:
#                         log.debug("Duplicate replay")
#                     else:
#                         replays.add(r)

#                 if len(replays) == min_games:
#                     break
#         return replays

# async def get_all_trackers(
#     self, guild: discord.Guild, match: Match
# ) -> list[TrackerLink]:
#     if not (match.home_team.players or match.away_team.players):
#         return []

#     tasks = []
#     trackers: list[TrackerLink] = []

#     if not (match.home_team.players and match.away_team.players):
#         return []

#     async with asyncio.TaskGroup() as tg:
#         for p in match.home_team.players:
#             log.debug(f"Fetching trackers for {p.name}")
#             tasks.append(
#                 tg.create_task(self.trackers(guild=guild, player=p.discord_id))
#             )

#         for p in match.away_team.players:
#             log.debug(f"Fetching trackers for {p.name}")
#             tasks.append(
#                 tg.create_task(self.trackers(guild=guild, player=p.discord_id))
#             )

#     for task in tasks:
#         trackers.extend(
#             [r for r in task.result() if r.status != TrackerLinksStatus.FAILED]
#         )
#     return trackers

# async def valid_replay(
#     self, match: Match, replay: ballchasing.models.Replay
# ) -> bool:
#     # Both team names are present
#     if not await validation.validate_team_names(match, replay):
#         return False
#     # Duration >= 300 seconds (5 minute game)
#     if replay.duration and replay.duration < 280:
#         log.debug(f"Bad replay duration: {replay.duration}")
#         return False
#     if not (replay.blue and replay.orange):
#         log.debug("No data for blue or orange team in replay")
#         return False
#     # Deep relay search should return stats
#     if not (replay.blue.stats and replay.orange.stats):
#         log.debug("Stats not found in replay")
#         return False
#     # You can't win a game without a goal
#     log.debug(
#         f"Blue Goals: {replay.blue.stats.core.goals} Orange Goals: {replay.orange.stats.core.goals}"
#     )
#     total_goals = replay.blue.stats.core.goals + replay.orange.stats.core.goals
#     if total_goals <= 0:
#         return False
#     return True

# async def team_win_count(
#     self, match: Match, replays: set[ballchasing.models.Replay]
# ) -> tuple[int, int]:
#     home_wins = 0
#     away_wins = 0

#     if not (match.home_team.name and match.away_team.name):
#         raise ValueError("Match is missing team name for one or both of the teams")

#     home_name = match.home_team.name.lower()
#     away_name = match.away_team.name.lower()
#     for r in replays:
#         if not (r.blue and r.orange):
#             raise AttributeError(
#                 f"Replay {r.id} is missing team data for blue or orange"
#             )
#         if not (r.blue.stats and r.orange.stats):
#             raise AttributeError(
#                 f"Replay {r.id} is missing stats data for blue or orange"
#             )
#         if not (r.blue.name and r.orange.name):
#             raise AttributeError(
#                 f"Replay {r.id} is missing team name data for blue or orange"
#             )
#         if r.blue.stats.core.goals > r.orange.stats.core.goals:
#             if home_name == r.blue.name.lower():
#                 home_wins += 1
#             else:
#                 away_wins += 1
#         else:
#             if away_name == r.orange.name.lower():
#                 away_wins += 1
#             else:
#                 home_wins += 1
#     return (home_wins, away_wins)
