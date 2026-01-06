import discord
import json
import os
from discord import app_commands
from discord.ext import commands
from glicko2.glicko2 import Player
from datetime import datetime
from dotenv import load_dotenv
import asyncio

# --- CONFIG ---fais-
load_dotenv()
TOKEN = os.environ["TOKEN"]
GUILD_ID = int(os.environ["GUILD_ID"])
ALLOWED_CHANNEL = int(os.environ["ALLOWED_CHANNEL"])
RESET_ROLE_ID = int(os.environ["RESET_ROLE_ID"])
MAUVAIS_CHANNEL_STRING = "❌ Commande uniquement dans le canal Smash."

# --- INTENTS ---
intents = discord.Intents.default()
intents.members = True

# --- BOT ---
class SmashBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="/",   
            intents=intents,
        )        
        self.players = {}

    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

bot = SmashBot()

class ConfirmMatchView(discord.ui.View):
    def __init__(self, winner: discord.Member, loser: discord.Member, timeout=120):
        super().__init__(timeout=timeout)
        self.winner = winner
        self.loser = loser
        self.confirmed = set()
        self.done = asyncio.Event()  # signal async


    @discord.ui.button(label="✅ Confirmer le match", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):

        if interaction.user.id not in (self.winner.id, self.loser.id):
            await interaction.response.send_message(
                "❌ Seuls les joueurs du match peuvent confirmer.",
                ephemeral=True
            )
            return

        self.confirmed.add(interaction.user.id)

        await interaction.response.send_message(
            f"✅ {interaction.user.display_name} a confirmé.",
            ephemeral=True
        )

        # Si les deux ont confirmé → on débloque
        if len(self.confirmed) == 2:
            self.done.set()
            self.stop()


# --- COMMANDES ---

# REPORT
@bot.tree.command(name="declare", description="Déclare un match")
async def declare(
    interaction: discord.Interaction,
    gagnant: discord.Member,
    perdant: discord.Member
):
    if not in_allowed_channel(interaction):
        await interaction.response.send_message(
            MAUVAIS_CHANNEL_STRING,
            ephemeral=True
        )
        return

    view = ConfirmMatchView(gagnant, perdant)

    await interaction.response.send_message(
        f"🥊Match déclaré : {gagnant.mention} a battu {perdant.mention}\n",
        view=view
    )

    # ⏳ attente async (NON bloquante)
    await view.done.wait()
    
    if len(view.confirmed) < 2:
        await interaction.followup.send(
            "⏰ Temps écoulé — match annulé."
        )
        return

    p_winner = get_player(gagnant)
    p_loser = get_player(perdant)

    p_winner_before = p_winner.rating
    p_loser_before = p_loser.rating

    p_winner.update_player([p_loser.rating], [p_loser.rd], [1])
    p_loser.update_player([p_winner.rating], [p_winner.rd], [0])

    save_players(bot)

    log_match(
        gagnant,
        perdant,
        p_winner_before,
        p_loser_before,
        p_winner.rating,
        p_loser.rating
    )

    await interaction.followup.send(
        f"✅ Match confirmé !\n"
        f"{gagnant.display_name}: {p_winner.rating:.1f}\n"
        f"{perdant.display_name}: {p_loser.rating:.1f}"
    )





# LEADERBOARD
@bot.tree.command(name="classement", description="Affiche le classement des joueurs")
async def classement(interaction: discord.Interaction):
    if interaction.channel_id != ALLOWED_CHANNEL:
        await interaction.response.send_message(
            MAUVAIS_CHANNEL_STRING,
            ephemeral=True
        )
        return
    
    if not bot.players:
        await interaction.response.send_message("Aucun joueur enregistré encore.")
        return

        
    sorted_players = sorted(
        bot.players.items(),
        key=lambda item: (item[1].rating - (2*item[1].rd)),
        reverse=True)
    
    lines = []
    for rank, (discord_id, player) in enumerate(sorted_players, start=1):
        name = await get_display_name(interaction, discord_id)

        lines.append(
            f"{rank:>2}. {name[:15]:<15} | {player.rating:>6.4g} | {player.rd:.3g}"
        )

    leaderboard_text = "```text\n   Nom              | Cote    | DC\n" \
                   "----------------------------------\n" + \
                   "\n".join(lines) + "\n```"

    await interaction.response.send_message(leaderboard_text)       


# --- FONCTIONS ANCILLAIRES ---
def get_player(member):
    if member.id not in bot.players:
        bot.players[member.id] = Player()
    return bot.players[member.id]

def load_players(bot, filename="players.json"):
    try:
        with open(filename, "r") as f:
            data = json.load(f)
        for discord_id, stats in data.items():
            p = Player()
            p.setRating(stats["rating"])
            p.setRd(stats["rd"])
            p.setVol(stats["volatility"])
            bot.players[int(discord_id)] = p
    except FileNotFoundError:
        bot.players = {}
        
def save_players(bot, filename="players.json"):
    data = {}
    for discord_id, player in bot.players.items():
        data[discord_id] = {
            "rating": player.rating,
            "rd": player.rd,
            "volatility": player.vol
        }
    with open(filename, "w") as f:
        json.dump(data, f, indent=4)

def log_match(winner, loser, p_winner_before, p_loser_before, p_winner_after, p_loser_after, filename="historique.json"):
    
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "winner_id": winner.id,
        "loser_id": loser.id,
        "winner_rating_before": p_winner_before,
        "winner_rating_after": p_winner_after,
        "loser_rating_before": p_loser_before,
        "loser_rating_after": p_loser_after,
    }
        
    try:
        with open(filename, "r") as f:
            history = json.load(f)
    except FileNotFoundError:
        history = []

    history.append(entry)

    with open(filename, "w") as f:
        json.dump(history, f, indent=4)
        
async def get_display_name(interaction, discord_id):
    member = interaction.guild.get_member(discord_id)
    if member:
        return member.display_name

    try:
        member = await interaction.guild.fetch_member(discord_id)
        return member.display_name
    except discord.NotFound:
        return f"id{discord_id}"

async def get_mention_str(interaction, discord_id):
    member = interaction.guild.get_member(discord_id)
    if member:
        return member.mention

    try:
        member = await interaction.guild.fetch_member(discord_id)
        return member.mention
    except discord.NotFound:
        return f"@<{discord_id}"

def in_allowed_channel(interaction: discord.Interaction):
    return interaction.channel_id == ALLOWED_CHANNEL


# --- START ---
load_players(bot)
@bot.event
async def on_ready():
    print(f"Connecté en tant que {bot.user}")

bot.run(TOKEN)