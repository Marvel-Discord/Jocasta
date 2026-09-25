import calendar, datetime, discord, itertools, math, pytz, re
from config import *
from discord import *
from discord.ext import commands
from discord.app_commands import *
from discord.app_commands.tree import _log


class TimeCog(discord.ext.commands.Cog, name = "Time"):
	"""Time commands"""

	def __init__(self, bot):
		self.bot = bot

		self.bot.tree.on_error = self.on_app_command_error


	datetosql = lambda self, x: x.strftime('%Y-%m-%d %H:%M:%S')
	strf = lambda self, x: x.strftime('%a, %b %d, %Y ~ %I:%M:%S %p %Z%z').replace(" 0", " ")
	# Sun, Mar 6, 2022 ~ 3:30 PM UTC
	s = lambda self, x: "" if x == 1 else "s"

	def strfdelta(self, tdelta):
		d = {}
		d["week"], d["day"] = divmod(tdelta.days, 7)
		d["hour"], rem = divmod(tdelta.seconds, 3600)
		d["minute"], d["second"] = divmod(rem, 60)
		return d
	def strfduration(self, tdt):
		txt = []
		for k, v in self.strfdelta(tdt).items():
			if v:
				txt.append(f"{v} {k}{self.s(v)}")
		return ', '.join(txt)


	async def on_app_command_error(self, interaction: Interaction, error: AppCommandError):
		if isinstance(error, app_commands.errors.CheckFailure):
			return await interaction.response.send_message(f"You can't use this command!", ephemeral = True)

		await interaction.followup.send("Something broke!")
		_log.error('Ignoring exception in command %r', interaction.command.name, exc_info=error)


	guild_ids = None if global_slashies else guild_ids

	timestampgroup = app_commands.Group(name="timestamp", description="Timestamp creation commands", guild_ids=guild_ids)


	async def autocomplete_timestamp_old(self, interaction: discord.Interaction, current: int):
		try:
			current = int(current)
		except ValueError:
			return []

		try:
			time = datetime.datetime.fromtimestamp(current, datetime.timezone.utc)
			return [app_commands.Choice(name = f"{self.strf(time)}", value = int(current))]
		except (OSError, OverflowError):
			return []

	async def autocomplete_timestamp(self, interaction: discord.Interaction, current: int):
		timestamp = self.strtodatetime(current)
		choices = [app_commands.Choice(name = self.strf(t), value = int(t.timestamp())) for t in timestamp]
		return choices[:25]

	async def autocomplete_duration(self, interaction: discord.Interaction, current: int, *, defaults = []):
		try:
			if current != "":
				current = float(current)
		except ValueError:
			return []

		ranges = {
			"seconds": "second",
			"minutes": "minute",
			"hours": "hour",
			"days": "day",
			"weeks": "week"
		}
		times = []

		if current != "":
			for k, v in ranges.items():
				try:
					times.append([datetime.timedelta(**{k: current}), current, v])
				except OverflowError:
					continue
		else:
			for t, n in defaults:
				try:
					times.append([datetime.timedelta(**{n: t}), t, ranges[n]])
				except OverflowError:
					continue

		choices = []
		for t in times:
			secs = int(round(t[0].total_seconds(), 0))
			if 15 <= secs <= 60480000: # Between 15s and 100w
				f = lambda x: x if isinstance(x, int) else (int(x) if x.is_integer() else x)
				choices.append(app_commands.Choice(name = f"{f(t[1])} {t[2]}{self.s(f(t[1]))}", value = int(secs)))
		return choices


	@timestampgroup.command(name="repeat")
	@app_commands.describe(
		starting_timestamp = "Timestamp to build upon.",
		interval = "The length of time between timestamps.",
		amount = "The number of timestamps to generate (including starting timestamp).",
		raw = "Display raw timestamp values only."
		)
	async def timestamprepeat(self, interaction: discord.Interaction, starting_timestamp: int, interval: int, amount: int, raw: bool = False):
		"""Lists following timestamps at constant intervals."""
		await interaction.response.defer()

		if amount > 100:
			return await interaction.followup.send("Please set an amount less than 100.")

		timestamps = [starting_timestamp + interval * i for i in range(amount)]
		times = [f"<t:{t}:F> `{t}`" for t in timestamps]

		if not raw:
			embed = discord.Embed(
				title = f"Recurring every {self.strfduration(datetime.timedelta(seconds=interval))}",
				description = '\n'.join(times)
				)
			await interaction.followup.send(embed=embed)
		else:
			await interaction.followup.send('\n'.join([str(i) for i in timestamps]))
		

	@timestamprepeat.autocomplete("starting_timestamp")
	async def timestamprepeat_autocomplete_starting_timestamp(self, interaction: discord.Interaction, current: int):
		return await self.autocomplete_timestamp(interaction, current)

	@timestamprepeat.autocomplete("interval")
	async def timestamprepeat_autocomplete_interval(self, interaction: discord.Interaction, current: int):
		return await self.autocomplete_duration(interaction, current,
			defaults = [
				[1, "weeks"],
				[1, "days"],
				[12, "hours"],
				[6, "hours"],
				[1, "hours"],
				[30, "minutes"]
			])


	@timestampgroup.command(name="generate")
	@app_commands.describe(
		time = "Written date and time to convert to timestamp.",
		raw = "Display raw timestamp values only."
		)
	async def timestampgenerate(self, interaction: discord.Interaction, time: str, raw: bool = False):
		"""Generates a timestamp from a written date and time."""
		await interaction.response.defer()

		timestamps = self.strtodatetime(time)

		if not raw:
			txt = ["<t:{0}:F> | `{0}`".format(int(i.timestamp())) for i in timestamps]
			embed = discord.Embed(description = '\n'.join(txt), colour = 0x2f3136)
			await interaction.followup.send(embed=embed)
		else:
			await interaction.followup.send('\n'.join(str(int(i.timestamp())) for i in timestamps))

	def strtodatetime(self, time: str):
		time = time.strip()

		if time.isdigit():
			try:
				time = int(time)
				return [datetime.datetime.fromtimestamp(time, datetime.timezone.utc)]
			except (OSError, OverflowError):
				return None

		kwargs = {i: set() for i in ['year', 'month', 'day', 'hour', 'minute', 'second']}

		segments = [i.strip(',') for i in time.split(" ")]

		today = datetime.datetime.utcnow()

		months = {index: [name.lower(), abbr.lower()] for index, (name, abbr) in enumerate(zip(calendar.month_name, calendar.month_abbr)) if name and abbr}

		for i in segments:
			j = i.strip("stndrh")
			if j.isdigit():
				i = int(j)
				if i >= 1970:
					kwargs['year'].add(i)
				elif i >= 1:
					kwargs['day'].add(i)
			else:
				kwargs['month'] |= {k for k, v in months.items() if i.lower() in v}

		ampm = None
		ampmkey = {True: ["a", "am"], False: ["p", "pm"]}
		for i in segments:
			try:
				ampm = next(k for k, v in ampmkey.items() if any(i.endswith(j) for j in v))
			except StopIteration:
				pass

		ignoreddates = set()

		for i in segments:
			i = i.replace("-", "/")

			if "/" in i:
				dates = i.split("/")
				if 2 <= len(dates) <= 3:
					if len(dates) == 3:
						for n, d in enumerate(dates):
							if d.isdigit() and (int(d) > 30 or n == 2):
								year = int(d)
								if year < 100: year += 2000
								if year < 1970: year = today.year
								else: kwargs['year'].add(year)
								dates.remove(d)
							else:
								year = today.year
					else: year = today.year

					ignoreddates.update([tuple([int(f)]) * 2 for f in dates[:2] if f.isdigit()])

					for ddmm in [dates[:2], [dates[1], dates[0]]]:
						try:
							ddmm = [int(d) for d in ddmm]
							datetime.datetime(year=year, month=ddmm[0], day=ddmm[1])
						except ValueError:
							continue
						else:
							kwargs['month'].add(ddmm[0])
							kwargs['day'].add(ddmm[1])
							if tuple(ddmm) in ignoreddates:
								ignoreddates -= {tuple(ddmm)}

			if (":" in i) or any(any(i.endswith(j) for j in v) for v in ampmkey.values()):
				times = i.strip('apm').split(":")
				if 1 <= len(times) <= 3:
					try:
						times = [int(float(t)) for t in times]
					except ValueError as e:
						pass
					else:
						if 0 <= times[0] <= 23:
							if ampm is True and times[0] >= 12:
								kwargs['hour'].add(times[0] - 12)
							elif (ampm is False or ampm is None) and times[0] < 12:
								kwargs['hour'].add(times[0] + 12)
							if (ampm is True and times[0] < 12) or (ampm is False and times[0] >= 12) or (ampm is None):
								kwargs['hour'].add(times[0])

						if len(times) >= 2 and 0 <= times[1] <= 59:
							kwargs['minute'].add(times[1])

						if len(times) >= 3 and 0 <= times[2] <= 59:
							kwargs['second'].add(times[2])

		hours = {"noon": 12, "midnight": 0, "morning": 8, "afternoon": 1, "evening": 9}
		for i in segments:
			if i.lower() in hours.keys():
				kwargs['hour'].add(hours[i.lower()])


		kwargs = {k: v if v else ({getattr(today, k)} if k in ['year', 'month', 'day'] else ({getattr(today, k)} if all(not kwargs[l] for l in ['hour', 'minute', 'day']) else {0})) for k, v in kwargs.items()}

		times = []
		timetz = []
		for i in list(itertools.product(*list(kwargs.values()))):
			values = {k: v for k, v in zip(kwargs.keys(), i)}
			if (values['month'], values['day']) in ignoreddates: continue
			try:
				times.append(datetime.datetime(**values))
			except ValueError:
				continue

		def tzsearch(abb, time = None):
			abb = abb.lower().replace("utc", "").rstrip("0").replace("+0", "+").replace("+", "+0")
			dsts = [abb, abb.replace("st", "dt"), abb.replace("dt", "st")]
			if abb.endswith('t'): dsts += [abb[:-1] + i for i in ['dt', 'st']]
			if time is None: time = datetime.datetime.now()

			tzs = [tz for tz in [pytz.timezone(i).localize(time) for i in pytz.all_timezones] if tz.tzname().lower() in dsts]

			offset = lambda i: i.tzinfo.utcoffset(i)
			dates = []
			for tz in tzs:
				if offset(tz) not in [offset(i) for i in dates]:
					dates.append(tz)

			return dates

		for t in times:
			tz = segments[-1].lower()
			if tz.startswith("gmt") and len(tz) > 3: tz = tz[3:]
			if tz.startswith("+") and not len(tz) % 2: tz = '+0' + tz[1:]
			timetz += tzsearch(tz, t)
			if not timetz:
				timetz += [pytz.utc.localize(t)]

		return timetz

	

	@timestampgenerate.autocomplete("time")
	async def timestampgenerate_autocomplete_time(self, interaction: discord.Interaction, current: str):
		choices = await self.autocomplete_timestamp(interaction, current)
		for i in choices:
			i.value = str(i.value)
		return choices


	@timestampgroup.command(name="event")
	@app_commands.describe(
		event = "Event to attain time.",
		show_end = "Show end time of event"
	)
	async def timestampevent(self, interaction: discord.Interaction, event: str, show_end: bool = False):
		"""Gives relational start time for events."""
		await interaction.response.defer()

		try:
			event = await interaction.guild.fetch_scheduled_event(int(event))
		except (ValueError, NotFound):
			return await interaction.followup.send("Event could not be found in this server.")

		start = int(event.start_time.timestamp())
		end = int(event.end_time.timestamp()) if show_end and event.end_time else None

		embed = discord.Embed(
			title = f"🗓️ | {event.name}",
			description = "Starts at **<t:{0}:F>**, <t:{0}:R>".format(start)
				+ ("\nEnds at <t:{0}:F>, <t:{0}:R>".format(end) if end else ""),
			colour = 0x2f3136
			)

		embed.set_footer(
			text = f"{start}" + (f" | {end}" if end else "")
			)

		await interaction.followup.send(event.url, embed=embed)

	@timestampevent.autocomplete("event")
	async def timestampevent_autocomplete_event(self, interaction: discord.Interaction, current: str):
		try:
			events = interaction.guild.scheduled_events
			if not events:
				await interaction.response.defer()
				events = await interaction.guild.fetch_scheduled_events()
			events = [i for i in events if i.status in [discord.EventStatus.scheduled, discord.EventStatus.active]]
			events.sort(key = lambda x: x.start_time.timestamp())
		except HTTPException: return []

		search = []

		if current:
			findid = re.split('=|/', current)[-1]
			if findid.isdigit():
				eventid = int(findid)
				try:
					event = next(i for i in events if i.id == eventid)
					search += [app_commands.Choice(name = event.name, value = str(event.id))]
				except StopIteration:
					search += [app_commands.Choice(name = f"Event with ID: {eventid}", value = str(eventid))]

			alnum = lambda x: re.sub(r'[\W_]+', '', x.lower()) if x else ''
			lowered = alnum(current)
			search += [app_commands.Choice(name = i.name, value = str(i.id)) for i in events if any(
				lowered in alnum(getattr(i, j)) for j in ['name', 'description']
			)]
		else:
			search = [app_commands.Choice(name = event.name, value = str(event.id)) for event in events]

		return search[:25]

		



async def setup(bot):
	await bot.add_cog(TimeCog(bot))