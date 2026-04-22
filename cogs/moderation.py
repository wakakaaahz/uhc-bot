import discord
from discord.ext import commands
from discord import app_commands
import json
import os


# ── Helper admin (même logique que ton bot.py) ─────────────────────────────────
def is_admin(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.administrator:
        return True
    try:
        with open("config.json", "r") as f:
            config = json.load(f)
        admin_role_id = config.get("admin_role_id")
        if admin_role_id:
            return any(r.id == admin_role_id for r in interaction.user.roles)
    except Exception:
        pass
    return False


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /clear ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="clear", description="Supprime des messages dans le salon")
    @app_commands.describe(nombre="Nombre de messages à supprimer (1–100)")
    async def clear(self, interaction: discord.Interaction, nombre: int):
        if not is_admin(interaction):
            await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
            return

        if not 1 <= nombre <= 100:
            await interaction.response.send_message("❌ Le nombre doit être entre **1** et **100**.", ephemeral=True)
            return

        if not interaction.channel.permissions_for(interaction.guild.me).manage_messages:
            await interaction.response.send_message("❌ Je n'ai pas la permission **Gérer les messages** dans ce salon.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        deleted = await interaction.channel.purge(limit=nombre)

        embed = discord.Embed(
            title="🧹 Salon nettoyé",
            description=f"**{len(deleted)}** message{'s' if len(deleted) > 1 else ''} supprimé{'s' if len(deleted) > 1 else ''}.",
            color=0x2ECC71,
        )
        embed.set_footer(text=f"Action effectuée par {interaction.user.display_name}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /kick ──────────────────────────────────────────────────────────────────
    @app_commands.command(name="kick", description="Expulse un membre du serveur")
    @app_commands.describe(membre="Le membre à expulser", raison="Raison de l'expulsion (optionnel)")
    async def kick(self, interaction: discord.Interaction, membre: discord.Member, raison: str = "Aucune raison fournie"):
        if not is_admin(interaction):
            await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
            return

        if membre == interaction.user:
            await interaction.response.send_message("❌ Tu ne peux pas te kick toi-même.", ephemeral=True)
            return

        if membre.top_role >= interaction.user.top_role and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Tu ne peux pas kick quelqu'un avec un rôle supérieur ou égal au tien.", ephemeral=True)
            return

        if not interaction.guild.me.guild_permissions.kick_members:
            await interaction.response.send_message("❌ Je n'ai pas la permission **Expulser des membres**.", ephemeral=True)
            return

        try:
            # DM au membre avant le kick
            try:
                dm_embed = discord.Embed(
                    title=f"👢 Tu as été expulsé de **{interaction.guild.name}**",
                    description=f"**Raison :** {raison}",
                    color=0xE67E22,
                )
                await membre.send(embed=dm_embed)
            except discord.Forbidden:
                pass  # Le membre a ses DMs fermés

            await membre.kick(reason=f"{raison} | Par {interaction.user}")

            embed = discord.Embed(
                title="👢 Membre expulsé",
                description=f"{membre.mention} a été expulsé du serveur.",
                color=0xE67E22,
            )
            embed.add_field(name="Raison", value=raison, inline=False)
            embed.add_field(name="Modérateur", value=interaction.user.mention, inline=False)
            embed.set_thumbnail(url=membre.display_avatar.url)
            await interaction.response.send_message(embed=embed)

        except discord.Forbidden:
            await interaction.response.send_message("❌ Je ne peux pas kick ce membre (rôle trop élevé ?).", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Erreur : `{e}`", ephemeral=True)

    # ── /ban ───────────────────────────────────────────────────────────────────
    @app_commands.command(name="ban", description="Bannit un membre du serveur")
    @app_commands.describe(
        membre="Le membre à bannir",
        raison="Raison du ban (optionnel)",
        supprimer_messages="Supprimer les messages des X derniers jours (0–7)",
    )
    async def ban(self, interaction: discord.Interaction, membre: discord.Member, raison: str = "Aucune raison fournie", supprimer_messages: int = 0):
        if not is_admin(interaction):
            await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
            return

        if membre == interaction.user:
            await interaction.response.send_message("❌ Tu ne peux pas te bannir toi-même.", ephemeral=True)
            return

        if membre.top_role >= interaction.user.top_role and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Tu ne peux pas bannir quelqu'un avec un rôle supérieur ou égal au tien.", ephemeral=True)
            return

        if not interaction.guild.me.guild_permissions.ban_members:
            await interaction.response.send_message("❌ Je n'ai pas la permission **Bannir des membres**.", ephemeral=True)
            return

        supprimer_messages = max(0, min(7, supprimer_messages))

        try:
            try:
                dm_embed = discord.Embed(
                    title=f"🔨 Tu as été banni de **{interaction.guild.name}**",
                    description=f"**Raison :** {raison}",
                    color=0xE74C3C,
                )
                await membre.send(embed=dm_embed)
            except discord.Forbidden:
                pass

            await membre.ban(reason=f"{raison} | Par {interaction.user}", delete_message_days=supprimer_messages)

            embed = discord.Embed(
                title="🔨 Membre banni",
                description=f"{membre.mention} a été banni du serveur.",
                color=0xE74C3C,
            )
            embed.add_field(name="Raison", value=raison, inline=False)
            embed.add_field(name="Modérateur", value=interaction.user.mention, inline=False)
            if supprimer_messages > 0:
                embed.add_field(name="Messages supprimés", value=f"{supprimer_messages} jour(s)", inline=False)
            embed.set_thumbnail(url=membre.display_avatar.url)
            await interaction.response.send_message(embed=embed)

        except discord.Forbidden:
            await interaction.response.send_message("❌ Je ne peux pas bannir ce membre (rôle trop élevé ?).", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Erreur : `{e}`", ephemeral=True)

    # ── /unban ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="unban", description="Débannit un utilisateur par son ID ou pseudo#tag")
    @app_commands.describe(utilisateur="ID Discord ou pseudo#discriminator (ex: 123456789 ou Hari#1234)")
    async def unban(self, interaction: discord.Interaction, utilisateur: str):
        if not is_admin(interaction):
            await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
            return

        if not interaction.guild.me.guild_permissions.ban_members:
            await interaction.response.send_message("❌ Je n'ai pas la permission **Bannir des membres**.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=False)

        bans = [entry async for entry in interaction.guild.bans()]
        target = None

        # Recherche par ID
        if utilisateur.isdigit():
            user_id = int(utilisateur)
            for ban_entry in bans:
                if ban_entry.user.id == user_id:
                    target = ban_entry.user
                    break
        else:
            # Recherche par pseudo (insensible à la casse)
            for ban_entry in bans:
                if ban_entry.user.name.lower() == utilisateur.lower():
                    target = ban_entry.user
                    break

        if target is None:
            await interaction.followup.send(f"❌ Aucun utilisateur banni trouvé pour `{utilisateur}`.", ephemeral=True)
            return

        try:
            await interaction.guild.unban(target)
            embed = discord.Embed(
                title="✅ Utilisateur débanni",
                description=f"**{target}** (`{target.id}`) a été débanni.",
                color=0x2ECC71,
            )
            embed.add_field(name="Modérateur", value=interaction.user.mention, inline=False)
            embed.set_thumbnail(url=target.display_avatar.url)
            await interaction.followup.send(embed=embed)

        except discord.Forbidden:
            await interaction.followup.send("❌ Je ne peux pas débannir cet utilisateur.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Erreur : `{e}`", ephemeral=True)

    # ── /timeout ───────────────────────────────────────────────────────────────
    @app_commands.command(name="timeout", description="Met un membre en timeout (muet temporaire)")
    @app_commands.describe(
        membre="Le membre à mettre en timeout",
        duree="Durée en minutes (max 40 320 = 28 jours)",
        raison="Raison du timeout (optionnel)",
    )
    async def timeout(self, interaction: discord.Interaction, membre: discord.Member, duree: int, raison: str = "Aucune raison fournie"):
        if not is_admin(interaction):
            await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
            return

        if membre == interaction.user:
            await interaction.response.send_message("❌ Tu ne peux pas te mettre en timeout toi-même.", ephemeral=True)
            return

        if membre.top_role >= interaction.user.top_role and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Tu ne peux pas timeout quelqu'un avec un rôle supérieur ou égal au tien.", ephemeral=True)
            return

        if not interaction.guild.me.guild_permissions.moderate_members:
            await interaction.response.send_message("❌ Je n'ai pas la permission **Mettre en sourdine les membres**.", ephemeral=True)
            return

        MAX_MINUTES = 40320  # 28 jours
        if not 1 <= duree <= MAX_MINUTES:
            await interaction.response.send_message(f"❌ La durée doit être entre **1** et **{MAX_MINUTES}** minutes.", ephemeral=True)
            return

        from datetime import timedelta
        duration = timedelta(minutes=duree)

        # Formatage lisible
        if duree < 60:
            duree_str = f"{duree} minute{'s' if duree > 1 else ''}"
        elif duree < 1440:
            h = duree // 60
            m = duree % 60
            duree_str = f"{h}h{m:02d}" if m else f"{h} heure{'s' if h > 1 else ''}"
        else:
            j = duree // 1440
            duree_str = f"{j} jour{'s' if j > 1 else ''}"

        try:
            try:
                dm_embed = discord.Embed(
                    title=f"🔇 Tu as été mis en timeout sur **{interaction.guild.name}**",
                    description=f"**Durée :** {duree_str}\n**Raison :** {raison}",
                    color=0xF39C12,
                )
                await membre.send(embed=dm_embed)
            except discord.Forbidden:
                pass

            await membre.timeout(duration, reason=f"{raison} | Par {interaction.user}")

            embed = discord.Embed(
                title="🔇 Membre mis en timeout",
                description=f"{membre.mention} ne peut plus envoyer de messages.",
                color=0xF39C12,
            )
            embed.add_field(name="Durée", value=duree_str, inline=True)
            embed.add_field(name="Raison", value=raison, inline=True)
            embed.add_field(name="Modérateur", value=interaction.user.mention, inline=False)
            embed.set_thumbnail(url=membre.display_avatar.url)
            await interaction.response.send_message(embed=embed)

        except discord.Forbidden:
            await interaction.response.send_message("❌ Je ne peux pas mettre ce membre en timeout.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Erreur : `{e}`", ephemeral=True)


# ── Setup ──────────────────────────────────────────────────────────────────────
async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))