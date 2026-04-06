import discord
from discord.ext import commands
from discord import app_commands
import json
import random
from datetime import datetime, timezone
import os
from dotenv import load_dotenv

# ── Chargement config ──────────────────────────────────────────────────────────
load_dotenv()

with open("config.json", "r") as f:
    config = json.load(f)

TOKEN         = os.getenv("DISCORD_TOKEN")
ADMIN_ROLE_ID = config["admin_role_id"]

# ── Grades & priorités ─────────────────────────────────────────────────────────
GRADES = {
    "VIP":      {"label": "👑 VIP",      "color": 0xFFD700, "priority": 2},
    "PRIORITY": {"label": "🔥 Priorité", "color": 0xFF6B00, "priority": 1},
    "NORMAL":   {"label": "👤 Normal",   "color": 0x95A5A6, "priority": 0},
}

# ── Stockage en mémoire ────────────────────────────────────────────────────────
active_events: dict = {}
user_grades:   dict = {}

# ── Persistance JSON ───────────────────────────────────────────────────────────
GRADES_FILE = "grades.json"

def load_grades():
    global user_grades
    if os.path.exists(GRADES_FILE):
        with open(GRADES_FILE, "r") as f:
            raw = json.load(f)
        user_grades = {int(g): {int(u): v for u, v in users.items()} for g, users in raw.items()}

def save_grades():
    with open(GRADES_FILE, "w") as f:
        json.dump({str(g): {str(u): v for u, v in users.items()} for g, users in user_grades.items()}, f, indent=2)

# ── Bot setup ──────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.reactions       = True
intents.members         = True

bot  = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ── Helpers ────────────────────────────────────────────────────────────────────
def is_admin(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.administrator:
        return True
    return any(r.id == ADMIN_ROLE_ID for r in interaction.user.roles)

def get_grade(guild_id: int, user_id: int) -> str:
    return user_grades.get(guild_id, {}).get(user_id, "NORMAL")

def format_countdown(pick_time_str: str) -> str:
    """Essaie de calculer un countdown depuis la chaîne pick_time."""
    formats = [
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %Hh%M",
        "%d/%m/%Y %Hh",
        "%Y-%m-%d %H:%M",
    ]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for fmt in formats:
        try:
            dt = datetime.strptime(pick_time_str.strip(), fmt)
            diff = dt - now
            total = int(diff.total_seconds())
            if total > 0:
                h, rem = divmod(total, 3600)
                m = rem // 60
                if h > 0:
                    return f"{pick_time_str} *(dans {h}h{m:02d})*"
                return f"{pick_time_str} *(dans {m} minutes)*"
        except ValueError:
            continue
    return pick_time_str

def build_embed(guild_id: int) -> discord.Embed:
    ev = active_events[guild_id]

    # Couleur orange vif comme la référence
    embed = discord.Embed(color=0xFF6B00)

    # Description style bullet points
    lines = []
    lines.append(f"🎮 · Mode de Jeu : **{ev['mode']}**")
    lines.append(f"👑 · Host : **{ev['host']}**")
    if ev.get("docs_url"):
        lines.append(f"📖 · Documents : **[{ev['docs_url']}]({ev['docs_url']})**")
    lines.append("")
    lines.append(f"📅 · Date et heure : **{ev['date']}**")
    lines.append(f"⏰ · Pick : **{format_countdown(ev['pick_time'])}**")
    lines.append("")
    lines.append(f"🎟️ · Slots : **{ev['slots']}**")
    lines.append(f"👥 · Participants : **{len(ev['participants'])}**")

    # Grades inscrits
    vips    = [f"<@{u}>" for u, g in ev["participants"].items() if g == "VIP"]
    prios   = [f"<@{u}>" for u, g in ev["participants"].items() if g == "PRIORITY"]
    normals = [f"<@{u}>" for u, g in ev["participants"].items() if g == "NORMAL"]

    if vips or prios or normals:
        lines.append("")
        if vips:
            lines.append("👑 **VIP (garanti)** : " + ", ".join(vips))
        if prios:
            lines.append("🔥 **Priorité** : " + ", ".join(prios))
        if normals:
            lines.append("👤 **Normal** : " + ", ".join(normals))

    if ev.get("rules_url"):
        lines.append("")
        lines.append(f"➡️ Règles : **[{ev['rules_url']}]({ev['rules_url']})**")

    embed.description = "\n".join(lines)

    # Image optionnelle
    if ev.get("image_url"):
        embed.set_image(url=ev["image_url"])

    embed.set_footer(text="🎲 Admission via un tirage au sort")
    return embed

# ── Tirage au sort ─────────────────────────────────────────────────────────────
async def do_pick(guild_id: int, channel: discord.TextChannel):
    ev = active_events[guild_id]
    if ev["picking_done"]:
        return
    ev["picking_done"] = True

    slots        = ev["slots"]
    participants = ev["participants"]

    vips    = [uid for uid, g in participants.items() if g == "VIP"]
    prios   = [uid for uid, g in participants.items() if g == "PRIORITY"]
    normals = [uid for uid, g in participants.items() if g == "NORMAL"]

    picked = list(vips)
    remaining_slots = slots - len(picked)
    if remaining_slots <= 0:
        picked = picked[:slots]
        remaining_slots = 0

    pool = prios * 2 + normals
    random.shuffle(pool)

    seen = set(picked)
    for uid in pool:
        if remaining_slots <= 0:
            break
        if uid not in seen:
            picked.append(uid)
            seen.add(uid)
            remaining_slots -= 1

    ev["picked"] = picked

    embed = discord.Embed(
        title="🎲 Résultats du tirage !",
        description=f"**{len(picked)}/{slots}** joueurs sélectionnés",
        color=0x2ECC71,
        timestamp=datetime.utcnow(),
    )

    if picked:
        embed.add_field(
            name="✅ Joueurs retenus",
            value="\n".join(
                f"{'👑' if participants.get(u)=='VIP' else '🔥' if participants.get(u)=='PRIORITY' else '🎮'} <@{u}>"
                for u in picked
            ),
            inline=False,
        )

    not_picked = [uid for uid in participants if uid not in seen]
    if not_picked:
        embed.add_field(
            name="❌ Non retenus",
            value=" ".join(f"<@{uid}>" for uid in not_picked),
            inline=False,
        )

    embed.set_footer(text="Bonne chance à tous ! ⚔️")
    await channel.send(embed=embed)

# ── Slash commands ─────────────────────────────────────────────────────────────

@tree.command(name="createevent", description="Crée un event UHC avec inscriptions")
@app_commands.describe(
    slots="Nombre de slots disponibles",
    mode="Mode de jeu (ex: All Stars UHC)",
    host="Nom du host",
    date="Date et heure de la game (ex: lundi 6 avril 2026 18:00)",
    pick_time="Heure du pick (ex: 06/04/2026 17:00)",
    docs_url="Lien vers les documents (optionnel)",
    rules_url="Lien vers les règles (optionnel)",
    image_url="Lien vers une image à afficher (optionnel)",
)
async def createevent(
    interaction: discord.Interaction,
    slots: int,
    mode: str,
    host: str,
    date: str,
    pick_time: str,
    docs_url:  str = "",
    rules_url: str = "",
    image_url: str = "",
):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
        return

    guild_id = interaction.guild_id
    if guild_id in active_events:
        await interaction.response.send_message("❌ Un event est déjà en cours ! Fais `/closeevent` d'abord.", ephemeral=True)
        return

    active_events[guild_id] = {
        "channel_id":   interaction.channel_id,
        "message_id":   None,
        "slots":        slots,
        "mode":         mode,
        "host":         host,
        "date":         date,
        "pick_time":    pick_time,
        "docs_url":     docs_url,
        "rules_url":    rules_url,
        "image_url":    image_url,
        "participants": {},
        "picked":       [],
        "picking_done": False,
    }

    await interaction.response.defer()
    embed = build_embed(guild_id)
    msg   = await interaction.followup.send(embed=embed)

    active_events[guild_id]["message_id"] = msg.id
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")

# ──────────────────────────────────────────────────────────────────────────────

@tree.command(name="pick", description="Lance le tirage au sort maintenant")
async def pick(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Permission refusée.", ephemeral=True)
        return

    guild_id = interaction.guild_id
    if guild_id not in active_events:
        await interaction.response.send_message("❌ Aucun event en cours.", ephemeral=True)
        return

    await interaction.response.send_message("🎲 Tirage en cours...", ephemeral=True)
    await do_pick(guild_id, interaction.channel)

# ──────────────────────────────────────────────────────────────────────────────

@tree.command(name="closeevent", description="Ferme l'event en cours")
async def closeevent(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Permission refusée.", ephemeral=True)
        return

    guild_id = interaction.guild_id
    if guild_id not in active_events:
        await interaction.response.send_message("❌ Aucun event en cours.", ephemeral=True)
        return

    del active_events[guild_id]
    await interaction.response.send_message("✅ Event fermé.", ephemeral=True)

# ──────────────────────────────────────────────────────────────────────────────

@tree.command(name="setgrade", description="Attribue un grade à un joueur")
@app_commands.describe(user="Le joueur", grade="VIP, PRIORITY ou NORMAL")
@app_commands.choices(grade=[
    app_commands.Choice(name="👑 VIP — Garanti pick",       value="VIP"),
    app_commands.Choice(name="🔥 Priorité — Double chance", value="PRIORITY"),
    app_commands.Choice(name="👤 Normal — Chance de base",  value="NORMAL"),
])
async def setgrade(interaction: discord.Interaction, user: discord.Member, grade: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Permission refusée.", ephemeral=True)
        return

    guild_id = interaction.guild_id
    if guild_id not in user_grades:
        user_grades[guild_id] = {}
    user_grades[guild_id][user.id] = grade
    save_grades()

    info = GRADES[grade]
    embed = discord.Embed(
        title="✅ Grade mis à jour",
        description=f"{user.mention} est maintenant **{info['label']}**",
        color=info["color"],
    )
    await interaction.response.send_message(embed=embed)

# ──────────────────────────────────────────────────────────────────────────────

@tree.command(name="grades", description="Affiche la liste des grades sur ce serveur")
async def grades_list(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    gdata    = user_grades.get(guild_id, {})

    if not gdata:
        await interaction.response.send_message("Aucun grade attribué pour l'instant.", ephemeral=True)
        return

    embed = discord.Embed(title="📋 Grades des joueurs", color=0x5865F2)
    for grade_key, info in GRADES.items():
        members = [f"<@{uid}>" for uid, g in gdata.items() if g == grade_key]
        if members:
            embed.add_field(name=info["label"], value=", ".join(members), inline=False)

    await interaction.response.send_message(embed=embed)

# ──────────────────────────────────────────────────────────────────────────────

@tree.command(name="participants", description="Affiche les inscrits de l'event en cours")
async def participants_cmd(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    if guild_id not in active_events:
        await interaction.response.send_message("❌ Aucun event en cours.", ephemeral=True)
        return

    embed = build_embed(guild_id)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ──────────────────────────────────────────────────────────────────────────────

@tree.command(name="help", description="Affiche l'aide du bot UHC")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 Aide — Bot UHC", color=0x5865F2)
    embed.add_field(
        name="🛠️ Commandes Admin",
        value=(
            "`/createevent` — Crée un event d'inscription\n"
            "`/pick` — Lance le tirage au sort maintenant\n"
            "`/closeevent` — Ferme l'event en cours\n"
            "`/setgrade @user grade` — Attribue un grade à un joueur\n"
        ),
        inline=False,
    )
    embed.add_field(
        name="👥 Commandes Joueurs",
        value=("`/participants` — Voir les inscrits\n""`/grades` — Voir tous les grades\n"),
        inline=False,
    )
    embed.add_field(
        name="🎖️ Système de Grades",
        value=(
            "**👑 VIP** — Toujours pick (100% garanti)\n"
            "**🔥 Priorité** — Double chance dans le tirage\n"
            "**👤 Normal** — Chance de base\n"
        ),
        inline=False,
    )
    embed.add_field(
        name="✅ ❌ Réactions",
        value="Réagis ✅ pour t'inscrire, ❌ pour te désinscrire.",
        inline=False,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ── Gestion des réactions ──────────────────────────────────────────────────────

async def refresh_event_message(guild_id: int):
    ev = active_events.get(guild_id)
    if not ev:
        return
    try:
        guild   = bot.get_guild(guild_id)
        channel = guild.get_channel(ev["channel_id"])
        message = await channel.fetch_message(ev["message_id"])
        await message.edit(embed=build_embed(guild_id))
    except Exception as e:
        print(f"[refresh] Erreur: {e}")

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return

    guild_id = payload.guild_id
    ev       = active_events.get(guild_id)
    if not ev or payload.message_id != ev["message_id"]:
        return

    if str(payload.emoji) == "✅":
        grade = get_grade(guild_id, payload.user_id)
        ev["participants"][payload.user_id] = grade
        await refresh_event_message(guild_id)

    elif str(payload.emoji) == "❌":
        ev["participants"].pop(payload.user_id, None)
        await refresh_event_message(guild_id)

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return

    guild_id = payload.guild_id
    ev       = active_events.get(guild_id)
    if not ev or payload.message_id != ev["message_id"]:
        return

    if str(payload.emoji) == "✅":
        ev["participants"].pop(payload.user_id, None)
        await refresh_event_message(guild_id)

# ── Démarrage ──────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    load_grades()
    await tree.sync()
    print(f"✅ Bot connecté en tant que {bot.user} (ID: {bot.user.id})")
    print("   Slash commands synchronisées.")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name="les games UHC ⚔️"
    ))

bot.run(TOKEN)