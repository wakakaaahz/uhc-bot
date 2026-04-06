import discord
from discord.ext import commands
from discord import app_commands
import json
import random
from datetime import datetime, timezone
import os
import aiohttp
from dotenv import load_dotenv

# ── Chargement config ──────────────────────────────────────────────────────────
load_dotenv()

with open("config.json", "r") as f:
    config = json.load(f)

TOKEN          = os.getenv("DISCORD_TOKEN")
ADMIN_ROLE_ID  = config["admin_role_id"]
CRAFTY_API_KEY = os.getenv("CRAFTY_API_KEY", "")  # Clé API crafty.gg (optionnelle)

# Lien documents fixe
DOCS_URL = "https://all-stars-arena.gitbook.io/alls-stars-arena/alls-stars-arena-1"

# ── Grades & priorités ─────────────────────────────────────────────────────────
GRADES = {
    "VIP":      {"label": "👑 VIP",      "color": 0xFFD700, "priority": 2},
    "PRIORITY": {"label": "🔥 Priorité", "color": 0xFF6B00, "priority": 1},
    "NORMAL":   {"label": "👤 Normal",   "color": 0x95A5A6, "priority": 0},
}

# ── Stockage en mémoire ────────────────────────────────────────────────────────
active_events: dict = {}
user_grades:   dict = {}
user_pseudos:  dict = {}

# ── Persistance JSON ───────────────────────────────────────────────────────────
GRADES_FILE  = "grades.json"
PSEUDOS_FILE = "pseudos.json"

def load_grades():
    global user_grades
    if os.path.exists(GRADES_FILE):
        with open(GRADES_FILE, "r") as f:
            raw = json.load(f)
        user_grades = {int(g): {int(u): v for u, v in users.items()} for g, users in raw.items()}

def save_grades():
    with open(GRADES_FILE, "w") as f:
        json.dump({str(g): {str(u): v for u, v in users.items()} for g, users in user_grades.items()}, f, indent=2)

def load_pseudos():
    global user_pseudos
    if os.path.exists(PSEUDOS_FILE):
        with open(PSEUDOS_FILE, "r") as f:
            raw = json.load(f)
        user_pseudos = {int(g): {int(u): v for u, v in users.items()} for g, users in raw.items()}

def save_pseudos():
    with open(PSEUDOS_FILE, "w") as f:
        json.dump({str(g): {str(u): v for u, v in users.items()} for g, users in user_pseudos.items()}, f, indent=2)

def get_pseudo(guild_id: int, user_id: int):
    return user_pseudos.get(guild_id, {}).get(user_id)

def has_pseudo(guild_id: int, user_id: int) -> bool:
    return user_id in user_pseudos.get(guild_id, {})

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
    formats = [
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %Hh%M",
        "%d/%m/%Y %Hh",
        "%Y-%m-%d %H:%M",
    ]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for fmt in formats:
        try:
            dt    = datetime.strptime(pick_time_str.strip(), fmt)
            diff  = dt - now
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
    embed = discord.Embed(color=0xFF6B00)

    lines = []
    lines.append(f"🎮 · **Mode de Jeu :** {ev['mode']}")
    host_display = f"<@{ev['host_id']}>" if ev.get("host_id") else ev["host"]
    lines.append(f"👑 · **Host :** {host_display}")
    lines.append(f"📖 · **Documents :** [Ouvrir le document]({DOCS_URL})")
    lines.append("")
    lines.append(f"📅 · **Date et heure :** {ev['date']}")
    lines.append(f"⏰ · **Pick :** {format_countdown(ev['pick_time'])}")
    lines.append("")
    lines.append(f"🎟️ · **Slots :** {ev['slots']}")
    lines.append(f"👥 · **Participants :** {len(ev['participants'])}")

    if ev.get("rules_url"):
        lines.append("")
        lines.append(f"➡️ **Règles :** [{ev['rules_url']}]({ev['rules_url']})")

    embed.description = "\n".join(lines)

    if ev.get("image_url"):
        embed.set_image(url=ev["image_url"])

    embed.set_footer(text="🎲 Admission via un tirage au sort  •  Fais /pseudo avant de t'inscrire !")
    return embed

# ── Vue avec boutons ───────────────────────────────────────────────────────────
class EventView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    @discord.ui.button(label="Rejoindre", emoji="✅", style=discord.ButtonStyle.success, custom_id="join_event")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        ev = active_events.get(self.guild_id)
        if not ev:
            await interaction.response.send_message("❌ Aucun event en cours.", ephemeral=True)
            return
        if not has_pseudo(self.guild_id, interaction.user.id):
            await interaction.response.send_message(
                "❌ Tu dois d'abord enregistrer ton pseudo Minecraft avec `/pseudo` avant de rejoindre !",
                ephemeral=True
            )
            return
        grade = get_grade(self.guild_id, interaction.user.id)
        ev["participants"][interaction.user.id] = grade
        pseudo = get_pseudo(self.guild_id, interaction.user.id)
        await interaction.response.send_message(
            f"✅ Tu es bien inscrit avec le pseudo **{pseudo}** !",
            ephemeral=True
        )
        await refresh_event_message(self.guild_id)

    @discord.ui.button(label="Quitter", emoji="❌", style=discord.ButtonStyle.danger, custom_id="leave_event")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        ev = active_events.get(self.guild_id)
        if not ev:
            await interaction.response.send_message("❌ Aucun event en cours.", ephemeral=True)
            return
        ev["participants"].pop(interaction.user.id, None)
        await interaction.response.send_message("❌ Tu as quitté l'event.", ephemeral=True)
        await refresh_event_message(self.guild_id)

    @discord.ui.button(label="Participants", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="show_participants")
    async def show_participants(self, interaction: discord.Interaction, button: discord.ui.Button):
        ev = active_events.get(self.guild_id)
        if not ev:
            await interaction.response.send_message("❌ Aucun event en cours.", ephemeral=True)
            return
        participants = ev["participants"]
        if not participants:
            await interaction.response.send_message("Aucun participant pour l'instant.", ephemeral=True)
            return

        vips    = [(u, g) for u, g in participants.items() if g == "VIP"]
        prios   = [(u, g) for u, g in participants.items() if g == "PRIORITY"]
        normals = [(u, g) for u, g in participants.items() if g == "NORMAL"]

        lines = [f"**📋 Participants ({len(participants)}/{ev['slots']})**\n"]

        def fmt(u):
            pseudo = get_pseudo(interaction.guild_id, u)
            ig = f" *(IG: {pseudo})*" if pseudo else ""
            return f"<@{u}>{ig}"

        if vips:
            lines.append("👑 **VIP (garanti)** :\n" + "\n".join(fmt(u) for u, _ in vips))
        if prios:
            lines.append("🔥 **Priorité** :\n" + "\n".join(fmt(u) for u, _ in prios))
        if normals:
            lines.append("👤 **Normal** :\n" + "\n".join(fmt(u) for u, _ in normals))

        await interaction.response.send_message("\n\n".join(lines), ephemeral=True)

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

    def format_player(uid):
        grade  = participants.get(uid, "NORMAL")
        emoji  = "👑" if grade == "VIP" else "🔥" if grade == "PRIORITY" else "🎮"
        pseudo = get_pseudo(guild_id, uid)
        ig     = f" **(IG: {pseudo})**" if pseudo else ""
        return f"{emoji} <@{uid}>{ig}"

    embed = discord.Embed(
        title="🎲 Résultats du tirage !",
        description=f"**{len(picked)}/{slots}** joueurs sélectionnés",
        color=0x2ECC71,
        timestamp=datetime.utcnow(),
    )
    if picked:
        embed.add_field(
            name="✅ Joueurs retenus",
            value="\n".join(format_player(u) for u in picked),
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

    guild = bot.get_guild(guild_id)
    if guild:
        category = guild.get_channel(ev["category_id"]) if ev.get("category_id") else None
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(send_messages=False, read_messages=True)
        }
        liste_channel = await guild.create_text_channel(
            name="liste",
            category=category,
            overwrites=overwrites,
            topic=f"Liste des joueurs pick pour {ev['mode']}"
        )
        lines = [f"# 📋 Liste des joueurs — {ev['mode']}\n"]
        for i, uid in enumerate(picked, 1):
            pseudo = get_pseudo(guild_id, uid)
            grade  = participants.get(uid, "NORMAL")
            emoji  = "👑" if grade == "VIP" else "🔥" if grade == "PRIORITY" else "🎮"
            ig     = f"**{pseudo}**" if pseudo else "*pseudo non renseigné*"
            lines.append(f"{i}. {emoji} <@{uid}> → {ig}")
        await liste_channel.send("\n".join(lines))

# ── Refresh embed ──────────────────────────────────────────────────────────────
async def refresh_event_message(guild_id: int):
    ev = active_events.get(guild_id)
    if not ev:
        return
    try:
        guild   = bot.get_guild(guild_id)
        channel = guild.get_channel(ev["channel_id"])
        message = await channel.fetch_message(ev["message_id"])
        await message.edit(embed=build_embed(guild_id), view=EventView(guild_id))
    except Exception as e:
        print(f"[refresh] Erreur: {e}")

# ── Historique pseudos — logique multi-sources ─────────────────────────────────
async def fetch_username_history(uuid_raw: str, current_name: str, session: aiohttp.ClientSession):
    """
    Tente de récupérer l'historique dans l'ordre :
    1. Crafty.gg  (le plus complet, nécessite CRAFTY_API_KEY)
    2. Laby.net
    3. Ashcon
    Retourne (history, source) où history = [{"username": str, "date_str": str|None}]
    """

    # ── 1. Crafty.gg ──────────────────────────────────────────────────────────
    if CRAFTY_API_KEY:
        try:
            headers = {
                "Authorization": f"Bearer {CRAFTY_API_KEY}",
                "User-Agent": "UHC-Bot/1.0",
            }
            crafty_url = f"https://api.crafty.gg/api/v2/players/{current_name}"
            async with session.get(crafty_url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # La réponse Crafty contient un champ "username_history" ou "names"
                    raw_history = (
                        data.get("data", {}).get("username_history")
                        or data.get("data", {}).get("names")
                        or data.get("username_history")
                        or []
                    )
                    if raw_history:
                        history = []
                        for entry in raw_history:
                            name = entry.get("username") or entry.get("name") or "?"
                            changed_at = entry.get("changed_at") or entry.get("date")
                            date_str = None
                            if changed_at:
                                try:
                                    # timestamp ms
                                    dt = datetime.utcfromtimestamp(int(changed_at) / 1000)
                                    date_str = dt.strftime("%d/%m/%Y")
                                except Exception:
                                    try:
                                        dt = datetime.strptime(str(changed_at)[:10], "%Y-%m-%d")
                                        date_str = dt.strftime("%d/%m/%Y")
                                    except Exception:
                                        pass
                            history.append({"username": name, "date_str": date_str})
                        if history:
                            return history, "Crafty.gg"
        except Exception as e:
            print(f"[crafty.gg] Erreur: {e}")

    # ── 2. Laby.net ───────────────────────────────────────────────────────────
    try:
        laby_url = f"https://laby.net/api/user/{uuid_raw}/get-names"
        async with session.get(laby_url) as resp:
            if resp.status == 200:
                laby_data = await resp.json()
                history = []
                for entry in laby_data:
                    name       = entry.get("name", "?")
                    changed_at = entry.get("changed_at")
                    date_str   = None
                    if changed_at:
                        try:
                            dt       = datetime.utcfromtimestamp(changed_at / 1000)
                            date_str = dt.strftime("%d/%m/%Y")
                        except Exception:
                            pass
                    history.append({"username": name, "date_str": date_str})
                if history:
                    return history, "Laby.net"
    except Exception as e:
        print(f"[laby.net] Erreur: {e}")

    # ── 3. Ashcon ─────────────────────────────────────────────────────────────
    try:
        ashcon_url = f"https://api.ashcon.app/mojang/v2/user/{uuid_raw}"
        async with session.get(ashcon_url) as resp:
            if resp.status == 200:
                ashcon_data = await resp.json()
                history = []
                for entry in ashcon_data.get("username_history", []):
                    name       = entry.get("username", "?")
                    changed_at = entry.get("changed_at")
                    date_str   = None
                    if changed_at:
                        try:
                            dt       = datetime.strptime(changed_at[:10], "%Y-%m-%d")
                            date_str = dt.strftime("%d/%m/%Y")
                        except Exception:
                            pass
                    history.append({"username": name, "date_str": date_str})
                if history:
                    return history, "Ashcon"
    except Exception as e:
        print(f"[ashcon] Erreur: {e}")

    return [], "Aucune source"

# ── Slash commands ─────────────────────────────────────────────────────────────

@tree.command(name="createevent", description="Crée un event UHC avec inscriptions")
@app_commands.describe(
    slots="Nombre de slots disponibles",
    mode="Mode de jeu (ex: AllStars)",
    host="Mentionne le host (@user)",
    date="Date et heure de la game (ex: lundi 6 avril 2026 18:00)",
    pick_time="Heure du pick format JJ/MM/AAAA HH:MM (ex: 06/04/2026 17:00)",
    rules_url="Lien vers les règles (optionnel)",
    image_url="Lien vers une image (optionnel)",
)
async def createevent(
    interaction: discord.Interaction,
    slots: int,
    mode: str,
    host: discord.Member,
    date: str,
    pick_time: str,
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

    await interaction.response.defer(ephemeral=True)

    guild = interaction.guild
    try:
        parts  = pick_time.strip().split(" ")
        h_part = parts[-1].replace(":", "h")
        if h_part.endswith("00"):
            h_part = h_part[:-2]
    except Exception:
        h_part = pick_time

    channel_name = f"{mode.replace(' ', '')}-{h_part}".lower()
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }
    event_channel = await guild.create_text_channel(
        name=channel_name,
        overwrites=overwrites,
        topic=f"Event {mode} — Pick à {pick_time}"
    )

    active_events[guild_id] = {
        "channel_id":   event_channel.id,
        "message_id":   None,
        "slots":        slots,
        "mode":         mode,
        "host":         host.display_name,
        "host_id":      host.id,
        "date":         date,
        "pick_time":    pick_time,
        "rules_url":    rules_url,
        "image_url":    image_url,
        "participants": {},
        "picked":       [],
        "picking_done": False,
        "category_id":  event_channel.category_id,
    }

    embed = build_embed(guild_id)
    msg   = await event_channel.send(embed=embed, view=EventView(guild_id))
    active_events[guild_id]["message_id"] = msg.id

    await interaction.followup.send(f"✅ Event créé dans {event_channel.mention} !", ephemeral=True)

# ──────────────────────────────────────────────────────────────────────────────

@tree.command(name="pseudo", description="Enregistre ton pseudo Minecraft")
@app_commands.describe(pseudo="Ton pseudo Minecraft (ex: Hari77)")
async def pseudo_cmd(interaction: discord.Interaction, pseudo: str):
    guild_id = interaction.guild_id
    if guild_id not in user_pseudos:
        user_pseudos[guild_id] = {}
    user_pseudos[guild_id][interaction.user.id] = pseudo
    save_pseudos()

    embed = discord.Embed(
        title="✅ Pseudo enregistré",
        description=f"{interaction.user.mention} → **IG: {pseudo}**",
        color=0x2ECC71,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ──────────────────────────────────────────────────────────────────────────────

@tree.command(name="historypseudo", description="[ADMIN] Affiche l'historique des pseudos d'un joueur Minecraft")
@app_commands.describe(pseudo="Le pseudo Minecraft actuel ou ancien du joueur")
async def historypseudo(interaction: discord.Interaction, pseudo: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    headers = {
        "User-Agent": "UHC-Bot/1.0 Mozilla/5.0"
    }

    async with aiohttp.ClientSession(headers=headers) as session:

        # 1) UUID via Mojang
        try:
            mojang_url = f"https://api.mojang.com/users/profiles/minecraft/{pseudo}"
            async with session.get(mojang_url) as resp:
                if resp.status == 404:
                    embed = discord.Embed(
                        title="❌ Joueur introuvable",
                        description=f"Le pseudo **{pseudo}** n'existe pas sur Minecraft.",
                        color=0xE74C3C,
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return
                if resp.status != 200:
                    raise Exception(f"Statut inattendu : {resp.status}")
                mojang_data = await resp.json()
        except Exception as e:
            embed = discord.Embed(
                title="❌ Erreur API Mojang",
                description=f"Impossible de contacter l'API Mojang.\n`{e}`",
                color=0xE74C3C,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        uuid_raw     = mojang_data["id"]
        uuid_fmt     = f"{uuid_raw[:8]}-{uuid_raw[8:12]}-{uuid_raw[12:16]}-{uuid_raw[16:20]}-{uuid_raw[20:]}"
        current_name = mojang_data["name"]

        # 2) Historique multi-sources
        username_history, source = await fetch_username_history(uuid_raw, current_name, session)

    # 3) Construction de l'embed
    embed = discord.Embed(
        title=f"📜 Historique de pseudos — {current_name}",
        color=0x5865F2,
    )

    avatar_url = f"https://crafatar.com/avatars/{uuid_raw}?size=64&overlay"
    embed.set_thumbnail(url=avatar_url)
    embed.add_field(name="🔑 UUID", value=f"`{uuid_fmt}`", inline=False)

    if not username_history:
        embed.add_field(
            name="📋 Historique",
            value="Aucun historique disponible (le joueur a peut-être tout caché).",
            inline=False,
        )
    else:
        history_lines = []
        total = len(username_history)
        for i, entry in enumerate(reversed(username_history)):
            name       = entry["username"]
            date_str   = entry["date_str"]
            is_current = (i == 0)
            date_part  = f" *(depuis le {date_str})*" if date_str else " *(pseudo d'origine)*"
            prefix     = "🟢" if is_current else f"`#{total - i}`"
            bold       = f"**{name}**" if is_current else name
            history_lines.append(f"{prefix} {bold}{date_part}")

        embed.add_field(
            name=f"📋 Historique ({total} pseudo{'s' if total > 1 else ''})",
            value="\n".join(history_lines),
            inline=False,
        )

    embed.add_field(
        name="🔗 Profil",
        value=(
            f"[Voir sur Crafty.gg](https://crafty.gg/@{current_name})  •  "
            f"[Voir sur Laby.net](https://laby.net/@{current_name})  •  "
            f"[Voir sur NameMC](https://namemc.com/profile/{uuid_raw})"
        ),
        inline=False,
    )

    embed.set_footer(text=f"Données : Mojang API & {source}  •  Avatar : Crafatar")
    await interaction.followup.send(embed=embed, ephemeral=True)

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

@tree.command(name="help", description="Affiche l'aide du bot UHC")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 Aide — Bot UHC", color=0x5865F2)
    embed.add_field(
        name="🛠️ Commandes Admin",
        value=(
            "`/createevent` — Crée un event + channel automatique\n"
            "`/pick` — Lance le tirage + crée le channel Liste\n"
            "`/closeevent` — Ferme l'event en cours\n"
            "`/setgrade @user grade` — Attribue un grade\n"
            "`/historypseudo` — Voir l'historique des pseudos Minecraft\n"
        ),
        inline=False,
    )
    embed.add_field(
        name="👥 Commandes Joueurs",
        value=(
            "`/pseudo` — Enregistre ton pseudo Minecraft (**obligatoire !**)\n"
            "`/grades` — Voir tous les grades\n"
        ),
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
        name="✅ ❌ Boutons",
        value=(
            "**Rejoindre** — S'inscrire *(pseudo MC obligatoire)*\n"
            "**Quitter** — Se désinscrire\n"
            "**Participants** — Voir la liste des inscrits"
        ),
        inline=False,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ── Démarrage ──────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    load_grades()
    load_pseudos()
    await tree.sync()
    print(f"✅ Bot connecté en tant que {bot.user} (ID: {bot.user.id})")
    print("   Slash commands synchronisées.")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name="les games UHC ⚔️"
    ))

bot.run(TOKEN)