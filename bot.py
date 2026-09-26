import ast
import asyncio
import os
import operator as op
import re
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
UPI_IMAGE_URL = os.getenv(
    "UPI_IMAGE_URL",
    "https://media.discordapp.net/attachments/1553271938347044904/1553324044772970616/Screenshot_2026-09-26-13-22-12-18_ba41e9a642e6e0e2b03656bfbbffd6e4.jpg?ex=6ab8d53f&is=6ab783bf&hm=0c2bdffd612a1fb72cb62393465329c41c19583847c5c2d3f4b67f6876c58948&=&format=webp",
)

if not DISCORD_TOKEN or not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Set DISCORD_TOKEN, SUPABASE_URL and SUPABASE_KEY.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

COINS = {
    "ltc": "LTC",
    "btc": "BTC",
    "eth": "ETH",
    "sol": "SOL",
    "usdt": "USDT",
    "bnb": "BNB",
    "xrp": "XRP",
    "doge": "DOGE",
    "trx": "TRX",
    "ton": "TON",
    "ada": "ADA",
    "dot": "DOT",
    "avax": "AVAX",
    "matic": "MATIC",
    "pol": "POL",
    "link": "LINK",
    "shib": "SHIB",
}

# ---------- Safe calculator ----------
BIN_OPS = {
    ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul,
    ast.Div: op.truediv, ast.FloorDiv: op.floordiv,
    ast.Mod: op.mod, ast.Pow: op.pow,
}
UNARY_OPS = {ast.UAdd: op.pos, ast.USub: op.neg}

def safe_calculate(expression: str):
    if len(expression) > 100:
        raise ValueError("Expression is too long.")
    tree = ast.parse(expression, mode="eval")

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if abs(node.value) > 10**100:
                raise ValueError("Number is too large.")
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in BIN_OPS:
            a, b = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(b) > 100:
                raise ValueError("Exponent is too large.")
            result = BIN_OPS[type(node.op)](a, b)
            if abs(result) > 10**100:
                raise ValueError("Result is too large.")
            return result
        if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY_OPS:
            return UNARY_OPS[type(node.op)](ev(node.operand))
        raise ValueError("Only basic arithmetic is allowed.")

    return ev(tree)

# ---------- Database ----------
def get_wallets(user_id: int) -> dict:
    res = supabase.table("wallets").select("*").eq("user_id", str(user_id)).limit(1).execute()
    return res.data[0] if res.data else {"user_id": str(user_id)}

def set_wallet(user_id: int, coin: str, address: str):
    existing = get_wallets(user_id)
    payload = {"user_id": str(user_id), coin: address, "updated_at": datetime.now(timezone.utc).isoformat()}
    if "id" in existing:
        supabase.table("wallets").update(payload).eq("user_id", str(user_id)).execute()
    else:
        supabase.table("wallets").insert(payload).execute()

# ---------- Bot ----------
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

class WalletModal(discord.ui.Modal):
    def __init__(self, coin: str):
        super().__init__(title=f"Configure {COINS[coin]} wallet")
        self.coin = coin
        self.address = discord.ui.TextInput(
            label=f"{COINS[coin]} address",
            placeholder="Paste your wallet address",
            required=True,
            max_length=256,
        )
        self.add_item(self.address)

    async def on_submit(self, interaction: discord.Interaction):
        address = self.address.value.strip()
        if len(address) < 8:
            await interaction.response.send_message("That address looks too short.", ephemeral=True)
            return
        try:
            set_wallet(interaction.user.id, self.coin, address)
            await interaction.response.send_message(
                f"✅ Your **{COINS[self.coin]}** address has been saved.",
                ephemeral=True,
            )
        except Exception as e:
            print("Supabase error:", e)
            await interaction.response.send_message(
                "❌ I couldn't save that address. Check the bot's Supabase configuration.",
                ephemeral=True,
            )

class ConfigureView(discord.ui.View):
    def __init__(self, coin: str):
        super().__init__(timeout=300)
        self.coin = coin

    @discord.ui.button(label="Configure", style=discord.ButtonStyle.primary)
    async def configure(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WalletModal(self.coin))

async def wallet_command(interaction: discord.Interaction, coin: str):
    try:
        wallets = get_wallets(interaction.user.id)
        address = wallets.get(coin)
    except Exception as e:
        print("Supabase error:", e)
        await interaction.response.send_message("❌ Database error.", ephemeral=True)
        return

    if not address:
        await interaction.response.send_message(
            f"⚠️ You haven't configured your **{COINS[coin]}** address yet.",
            view=ConfigureView(coin),
            ephemeral=True,
        )
        return

    embed = discord.Embed(title=f"{COINS[coin]} Address", description=f"`{address}`")
    embed.set_footer(text="Only send funds compatible with this network/address.")
    await interaction.response.send_message(embed=embed, ephemeral=True)

def make_coin_command(coin):
    async def command(interaction: discord.Interaction):
        await wallet_command(interaction, coin)
    return command

# ---------- Commands ----------
@bot.tree.command(name="checktx", description="Check a blockchain transaction by TXID/hash.")
@app_commands.describe(txid="Transaction ID/hash", network="Blockchain network")
@app_commands.choices(network=[
    app_commands.Choice(name="Bitcoin", value="btc"),
    app_commands.Choice(name="Litecoin", value="ltc"),
    app_commands.Choice(name="Ethereum", value="eth"),
    app_commands.Choice(name="Solana", value="sol"),
    app_commands.Choice(name="BNB Chain", value="bnb"),
    app_commands.Choice(name="TRON", value="trx"),
])
async def checktx(interaction: discord.Interaction, txid: str, network: app_commands.Choice[str]):
    await interaction.response.defer(ephemeral=True)
    # Provider-neutral implementation: validates input and returns an explorer link.
    # Add an RPC/indexer provider later for live status/confirmations.
    explorers = {
        "btc": f"https://mempool.space/tx/{txid}",
        "ltc": f"https://blockchair.com/litecoin/transaction/{txid}",
        "eth": f"https://etherscan.io/tx/{txid}",
        "sol": f"https://solscan.io/tx/{txid}",
        "bnb": f"https://bscscan.com/tx/{txid}",
        "trx": f"https://tronscan.org/#/transaction/{txid}",
    }
    if not re.fullmatch(r"[A-Za-z0-9:_-]{20,300}", txid):
        await interaction.followup.send("❌ That doesn't look like a valid transaction hash.", ephemeral=True)
        return
    embed = discord.Embed(
        title=f"{network.name} transaction",
        description=f"**TXID:** `{txid}`\n\n[Open transaction explorer]({explorers[network.value]})",
    )
    embed.set_footer(text="Explorer link generated. Live confirmation data requires an RPC/indexer API.")
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="upi", description="Show the UPI payment information.")
async def upi(interaction: discord.Interaction):
    embed = discord.Embed(title="UPI Payment")
    embed.set_image(url=UPI_IMAGE_URL)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="calculate", description="Calculate a basic arithmetic expression.")
@app_commands.describe(expression="Example: (25 * 4) + 10 / 2")
async def calculate(interaction: discord.Interaction, expression: str):
    try:
        result = safe_calculate(expression)
        await interaction.response.send_message(f"🧮 `{expression}` = **{result}**", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ {e}", ephemeral=True)

@bot.tree.command(name="info", description="Show your configured crypto addresses.")
async def info(interaction: discord.Interaction):
    try:
        wallets = get_wallets(interaction.user.id)
    except Exception as e:
        print("Supabase error:", e)
        await interaction.response.send_message("❌ Database error.", ephemeral=True)
        return

    lines = []
    for key, name in COINS.items():
        address = wallets.get(key)
        lines.append(f"**{name}:** {'✅ Configured' if address else '❌ Not configured'}")

    embed = discord.Embed(title="Your Crypto Configuration", description="\n".join(lines))
    embed.set_footer(text="Use /<coin> to view or configure an address.")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="help", description="Show all bot commands.")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="🤖 Crypto Bot Help")
    embed.description = (
        "**/checktx** — Check a transaction hash and open its explorer.\n"
        "**/ltc /btc /eth /sol /usdt /bnb /xrp /doge /trx /ton /ada /dot /avax /matic /pol /link /shib** — View or configure your address.\n"
        "**/upi** — Show UPI payment information.\n"
        "**/calculate** — Safely calculate basic arithmetic.\n"
        "**/info** — Show which wallet addresses you have configured.\n"
        "**/help** — Show this help menu."
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

for coin in COINS:
    cmd = app_commands.Command(
        name=coin,
        description=f"View or configure your {COINS[coin]} address.",
        callback=make_coin_command(coin),
    )
    bot.tree.add_command(cmd)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} global application commands.")
    except Exception as e:
        print("Command sync error:", e)

bot.run(DISCORD_TOKEN)
