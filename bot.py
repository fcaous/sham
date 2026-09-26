import os
import ast
import operator as op
import re
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

UPI_IMAGE_URL = os.getenv(
    "UPI_IMAGE_URL",
    "https://media.discordapp.net/attachments/1553271938347044904/1553324044772970616/Screenshot_2026-09-26-13-22-12-18_ba41e9a642e6e0e2b03656bfbbffd6e4.jpg?ex=6ab8d53f&is=6ab783bf&hm=0c2bdffd612a1fb72cb62393465329c41c19583847c5c2d3f4b67f6876c58948&=&format=webp",
)

missing = [name for name, value in {
    "DISCORD_TOKEN": DISCORD_TOKEN,
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_KEY": SUPABASE_KEY,
}.items() if not value]

if missing:
    raise RuntimeError(
        "Missing Render environment variable(s): "
        + ", ".join(missing)
        + ". Add them in Render -> Service -> Environment and redeploy."
    )

try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as exc:
    raise RuntimeError(
        "Could not initialize Supabase. Check SUPABASE_URL and SUPABASE_KEY."
    ) from exc

COINS = {
    "ltc": "LTC", "btc": "BTC", "eth": "ETH", "sol": "SOL",
    "usdt": "USDT", "bnb": "BNB", "xrp": "XRP", "doge": "DOGE",
    "trx": "TRX", "ton": "TON", "ada": "ADA", "dot": "DOT",
    "avax": "AVAX", "matic": "MATIC", "pol": "POL", "link": "LINK",
    "shib": "SHIB",
}

BIN_OPS = {
    ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul,
    ast.Div: op.truediv, ast.FloorDiv: op.floordiv,
    ast.Mod: op.mod, ast.Pow: op.pow,
}
UNARY_OPS = {ast.UAdd: op.pos, ast.USub: op.neg}

def safe_calculate(expression):
    expression = expression.strip()
    if not expression:
        raise ValueError("Enter a calculation.")
    if len(expression) > 100:
        raise ValueError("Calculation is too long.")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        raise ValueError("Invalid calculation.")

    def evaluate(node):
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if abs(node.value) > 10**100:
                raise ValueError("Number is too large.")
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in BIN_OPS:
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("Exponent is too large.")
            try:
                result = BIN_OPS[type(node.op)](left, right)
            except ZeroDivisionError:
                raise ValueError("You can't divide by zero.")
            if isinstance(result, (int, float)) and abs(result) > 10**100:
                raise ValueError("Result is too large.")
            return result
        if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY_OPS:
            return UNARY_OPS[type(node.op)](evaluate(node.operand))
        raise ValueError("Only basic arithmetic is supported.")
    return evaluate(tree)

def get_wallets(user_id):
    result = (
        supabase.table("wallets")
        .select("*")
        .eq("user_id", str(user_id))
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else {"user_id": str(user_id)}

def save_wallet(user_id, coin, address):
    now = datetime.now(timezone.utc).isoformat()
    existing = get_wallets(user_id)
    if "id" in existing:
        (
            supabase.table("wallets")
            .update({coin: address, "updated_at": now})
            .eq("user_id", str(user_id))
            .execute()
        )
    else:
        (
            supabase.table("wallets")
            .insert({"user_id": str(user_id), coin: address, "updated_at": now})
            .execute()
        )

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

class WalletModal(discord.ui.Modal):
    def __init__(self, coin):
        super().__init__(title=f"Configure {COINS[coin]}")
        self.coin = coin
        self.address_input = discord.ui.TextInput(
            label=f"{COINS[coin]} address",
            placeholder="Paste your wallet address here",
            required=True,
            min_length=8,
            max_length=256,
        )
        self.add_item(self.address_input)

    async def on_submit(self, interaction):
        address = self.address_input.value.strip()
        try:
            save_wallet(interaction.user.id, self.coin, address)
            await interaction.response.send_message(
                f"✅ Your **{COINS[self.coin]}** address has been saved.",
                ephemeral=True,
            )
        except Exception as exc:
            print("Supabase save error:", repr(exc))
            await interaction.response.send_message(
                "❌ Couldn't save the address. Check the Supabase table and key.",
                ephemeral=True,
            )

class ConfigureView(discord.ui.View):
    def __init__(self, coin):
        super().__init__(timeout=300)
        self.coin = coin

    @discord.ui.button(label="Configure", style=discord.ButtonStyle.primary, emoji="⚙️")
    async def configure(self, interaction, button):
        await interaction.response.send_modal(WalletModal(self.coin))

async def show_wallet(interaction, coin):
    try:
        wallets = get_wallets(interaction.user.id)
        address = wallets.get(coin)
    except Exception as exc:
        print("Supabase read error:", repr(exc))
        await interaction.response.send_message("❌ Database error.", ephemeral=True)
        return

    if not address:
        await interaction.response.send_message(
            f"⚠️ You haven't configured your **{COINS[coin]}** address yet.",
            view=ConfigureView(coin),
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title=f"{COINS[coin]} Address",
        description=f"`{address}`",
    )
    embed.set_footer(text="Make sure the network is correct before sending funds.")
    await interaction.response.send_message(embed=embed, ephemeral=True)

def wallet_callback(coin):
    async def callback(interaction):
        await show_wallet(interaction, coin)
    return callback

for coin in COINS:
    bot.tree.add_command(app_commands.Command(
        name=coin,
        description=f"View or configure your {COINS[coin]} address.",
        callback=wallet_callback(coin),
    ))

@bot.tree.command(name="checktx", description="Check a blockchain transaction.")
@app_commands.describe(txid="Transaction ID / hash", network="Blockchain network")
@app_commands.choices(network=[
    app_commands.Choice(name="Bitcoin", value="btc"),
    app_commands.Choice(name="Litecoin", value="ltc"),
    app_commands.Choice(name="Ethereum", value="eth"),
    app_commands.Choice(name="Solana", value="sol"),
    app_commands.Choice(name="BNB Chain", value="bnb"),
    app_commands.Choice(name="TRON", value="trx"),
])
async def checktx(interaction, txid, network):
    await interaction.response.defer(ephemeral=True)
    txid = txid.strip()

    if not re.fullmatch(r"[A-Za-z0-9:_-]{20,300}", txid):
        await interaction.followup.send(
            "❌ That doesn't look like a valid transaction hash.",
            ephemeral=True,
        )
        return

    explorers = {
        "btc": f"https://mempool.space/tx/{txid}",
        "ltc": f"https://blockchair.com/litecoin/transaction/{txid}",
        "eth": f"https://etherscan.io/tx/{txid}",
        "sol": f"https://solscan.io/tx/{txid}",
        "bnb": f"https://bscscan.com/tx/{txid}",
        "trx": f"https://tronscan.org/#/transaction/{txid}",
    }

    embed = discord.Embed(
        title=f"{network.name} Transaction",
        description=(
            f"**TXID:**\n`{txid}`\n\n"
            f"[🔎 Open transaction explorer]({explorers[network.value]})"
        ),
    )
    embed.set_footer(text="Live confirmation data requires an RPC/indexer.")
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="upi", description="Show UPI payment information.")
async def upi(interaction):
    embed = discord.Embed(title="UPI Payment")
    embed.set_image(url=UPI_IMAGE_URL)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="calculate", description="Calculate a basic arithmetic expression.")
@app_commands.describe(expression="Example: (25 * 4) + 10 / 2")
async def calculate(interaction, expression):
    try:
        result = safe_calculate(expression)
        await interaction.response.send_message(
            f"🧮 `{expression}` = **{result}**", ephemeral=True
        )
    except ValueError as exc:
        await interaction.response.send_message(f"❌ {exc}", ephemeral=True)

@bot.tree.command(name="info", description="Show your configured crypto addresses.")
async def info(interaction):
    try:
        wallets = get_wallets(interaction.user.id)
    except Exception as exc:
        print("Supabase info error:", repr(exc))
        await interaction.response.send_message("❌ Database error.", ephemeral=True)
        return

    lines = [
        f"**{name}:** {'✅ Configured' if wallets.get(coin) else '❌ Not configured'}"
        for coin, name in COINS.items()
    ]
    embed = discord.Embed(
        title="📋 Your Crypto Configuration",
        description="\n".join(lines),
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="help", description="Show all available bot commands.")
async def help_command(interaction):
    embed = discord.Embed(
        title="🤖 Crypto Bot Help",
        description=(
            "**/checktx** — Check a transaction.\n"
            "**/ltc /btc /eth /sol /usdt /bnb /xrp /doge /trx /ton** — "
            "View or configure your address.\n"
            "**/ada /dot /avax /matic /pol /link /shib** — More wallet commands.\n"
            "**/upi** — Show UPI payment information.\n"
            "**/calculate** — Calculate arithmetic.\n"
            "**/info** — Show your configured wallets.\n"
            "**/help** — Show this help menu."
        ),
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.event
async def on_ready():
    print("=" * 60)
    print(f"Logged in as: {bot.user} ({bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"Application commands synced: {len(synced)}")
        print("Commands:", ", ".join(f"/{c.name}" for c in synced))
    except Exception as exc:
        print("COMMAND SYNC FAILED:", repr(exc))
        print("Make sure the Discord application has the applications.commands scope.")
    print("=" * 60)

print("Starting Crypto Discord Bot...")
print("Python:", os.sys.version.split()[0])

try:
    bot.run(DISCORD_TOKEN)
except discord.LoginFailure as exc:
    raise RuntimeError(
        "Discord rejected DISCORD_TOKEN. Check the Render environment variable."
    ) from exc
except Exception:
    print("BOT CRASHED.")
    raise
