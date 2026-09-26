import os
import ast
import operator as op
import re
import threading
from datetime import datetime, timezone

from flask import Flask
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from supabase import create_client, Client

# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

UPI_IMAGE_URL = os.getenv(
    "UPI_IMAGE_URL",
    "https://media.discordapp.net/attachments/1553271938347044904/1553324044772970616/"
    "Screenshot_2026-09-26-13-22-12-18_ba41e9a642e6e0e2b03656bfbbffd6e4.jpg"
    "?ex=6ab8d53f&is=6ab783bf&hm=0c2bdffd612a1fb72cb62393465329c41c19583847c5c2d3f4b67f6876c58948&=&format=webp",
)

missing = [
    name
    for name, value in {
        "DISCORD_TOKEN": DISCORD_TOKEN,
        "SUPABASE_URL": SUPABASE_URL,
        "SUPABASE_KEY": SUPABASE_KEY,
    }.items()
    if not value
]

if missing:
    raise RuntimeError(
        "Missing environment variable(s): "
        + ", ".join(missing)
        + ". Add them in Render -> Environment and redeploy."
    )

try:
    supabase: Client = create_client(
        SUPABASE_URL,
        SUPABASE_KEY,
    )
except Exception as exc:
    raise RuntimeError(
        "Could not initialize Supabase. Check SUPABASE_URL and SUPABASE_KEY."
    ) from exc


# ============================================================
# RENDER WEB SERVICE HEALTH SERVER
# ============================================================

# Render Web Services expect the process to listen on PORT.
# This tiny Flask server exists only to satisfy that requirement.
# The Discord bot still does all of the actual work.

web_app = Flask(__name__)


@web_app.get("/")
def home():
    return "Discord bot is online!", 200


@web_app.get("/health")
def health():
    return "OK", 200


def run_web_server():
    port = int(os.getenv("PORT", "10000"))

    web_app.run(
        host="0.0.0.0",
        port=port,
        use_reloader=False,
    )


# ============================================================
# COINS
# ============================================================

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


# ============================================================
# SAFE CALCULATOR
# ============================================================

BINARY_OPERATORS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.FloorDiv: op.floordiv,
    ast.Mod: op.mod,
    ast.Pow: op.pow,
}

UNARY_OPERATORS = {
    ast.UAdd: op.pos,
    ast.USub: op.neg,
}


def safe_calculate(expression: str):
    expression = expression.strip()

    if not expression:
        raise ValueError("Enter a calculation.")

    if len(expression) > 100:
        raise ValueError("The calculation is too long.")

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        raise ValueError("Invalid calculation.")

    def evaluate(node):
        if isinstance(node, ast.Expression):
            return evaluate(node.body)

        if isinstance(node, ast.Constant) and isinstance(
            node.value,
            (int, float),
        ):
            if abs(node.value) > 10**100:
                raise ValueError("Number is too large.")
            return node.value

        if isinstance(node, ast.BinOp) and type(node.op) in BINARY_OPERATORS:
            left = evaluate(node.left)
            right = evaluate(node.right)

            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("Exponent is too large.")

            try:
                result = BINARY_OPERATORS[type(node.op)](left, right)
            except ZeroDivisionError:
                raise ValueError("You can't divide by zero.")

            if isinstance(result, (int, float)) and abs(result) > 10**100:
                raise ValueError("Result is too large.")

            return result

        if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY_OPERATORS:
            return UNARY_OPERATORS[type(node.op)](
                evaluate(node.operand)
            )

        raise ValueError("Only basic arithmetic is supported.")

    return evaluate(tree)


# ============================================================
# SUPABASE
# ============================================================

def get_wallets(user_id: int) -> dict:
    result = (
        supabase
        .table("wallets")
        .select("*")
        .eq("user_id", str(user_id))
        .limit(1)
        .execute()
    )

    if result.data:
        return result.data[0]

    return {"user_id": str(user_id)}


def save_wallet(user_id: int, coin: str, address: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    existing = get_wallets(user_id)

    if "id" in existing:
        (
            supabase
            .table("wallets")
            .update({
                coin: address,
                "updated_at": now,
            })
            .eq("user_id", str(user_id))
            .execute()
        )
    else:
        (
            supabase
            .table("wallets")
            .insert({
                "user_id": str(user_id),
                coin: address,
                "updated_at": now,
            })
            .execute()
        )


# ============================================================
# DISCORD
# ============================================================

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
)


# ============================================================
# WALLET MODAL
# ============================================================

class WalletModal(discord.ui.Modal):
    def __init__(self, coin: str):
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

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        address = self.address_input.value.strip()

        try:
            save_wallet(
                interaction.user.id,
                self.coin,
                address,
            )

            await interaction.response.send_message(
                f"✅ Your **{COINS[self.coin]}** address has been saved.",
                ephemeral=False,
            )

        except Exception as exc:
            print("Supabase save error:", repr(exc))

            await interaction.response.send_message(
                "❌ I couldn't save your address. Check your Supabase table and key.",
                ephemeral=True,
            )


# ============================================================
# CONFIGURE BUTTON
# ============================================================

class ConfigureWalletView(discord.ui.View):
    def __init__(self, coin: str):
        super().__init__(timeout=300)
        self.coin = coin

    @discord.ui.button(
        label="Configure",
        style=discord.ButtonStyle.primary,
        emoji="⚙️",
    )
    async def configure(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            WalletModal(self.coin)
        )


# ============================================================
# SHOW WALLET
# ============================================================

async def show_wallet(
    interaction: discord.Interaction,
    coin: str,
) -> None:
    try:
        wallets = get_wallets(interaction.user.id)
        address = wallets.get(coin)

    except Exception as exc:
        print("Supabase read error:", repr(exc))

        await interaction.response.send_message(
            "❌ Database error. Check your Supabase configuration.",
            ephemeral=True,
        )
        return

    if not address:
        await interaction.response.send_message(
            f"⚠️ You haven't configured your **{COINS[coin]}** address yet.",
            view=ConfigureWalletView(coin),
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title=f"{COINS[coin]} Address",
        description=f"`{address}`",
    )

    embed.set_footer(
        text="Make sure the network is correct before sending funds."
    )

    # PUBLIC: everyone in the channel can see the wallet address.
    await interaction.response.send_message(
        embed=embed,
        ephemeral=False,
    )


# ============================================================
# DYNAMIC WALLET COMMANDS
# ============================================================

def make_wallet_callback(coin: str):
    async def callback(
        interaction: discord.Interaction,
    ) -> None:
        await show_wallet(
            interaction,
            coin,
        )

    return callback


for coin in COINS:
    bot.tree.add_command(
        app_commands.Command(
            name=coin,
            description=f"View or configure your {COINS[coin]} address.",
            callback=make_wallet_callback(coin),
        )
    )


# ============================================================
# /CHECKTX
# ============================================================

@bot.tree.command(
    name="checktx",
    description="Check a blockchain transaction.",
)
@app_commands.describe(
    txid="Transaction ID / transaction hash",
    network="Blockchain network",
)
@app_commands.choices(
    network=[
        app_commands.Choice(name="Bitcoin", value="btc"),
        app_commands.Choice(name="Litecoin", value="ltc"),
        app_commands.Choice(name="Ethereum", value="eth"),
        app_commands.Choice(name="Solana", value="sol"),
        app_commands.Choice(name="BNB Chain", value="bnb"),
        app_commands.Choice(name="TRON", value="trx"),
    ]
)
async def checktx(
    interaction: discord.Interaction,
    txid: str,
    network: app_commands.Choice[str],
) -> None:
    await interaction.response.defer(ephemeral=False)

    txid = txid.strip()

    if not re.fullmatch(r"[A-Za-z0-9:_-]{20,300}", txid):
        await interaction.followup.send(
            "❌ That doesn't look like a valid transaction hash.",
            ephemeral=False,
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
            f"**TXID:**\n"
            f"`{txid}`\n\n"
            f"[🔎 Open transaction explorer]"
            f"({explorers[network.value]})"
        ),
    )

    embed.set_footer(
        text="Live confirmation data requires an RPC/indexer."
    )

    # PUBLIC: everyone can see the transaction result.
    await interaction.followup.send(
        embed=embed,
        ephemeral=False,
    )


# ============================================================
# /UPI
# ============================================================

@bot.tree.command(
    name="upi",
    description="Show UPI payment information.",
)
async def upi(
    interaction: discord.Interaction,
) -> None:
    embed = discord.Embed(
        title="UPI Payment",
        description="Use the payment information shown below.",
    )

    embed.set_image(url=UPI_IMAGE_URL)

    # PUBLIC
    await interaction.response.send_message(
        embed=embed,
        ephemeral=False,
    )


# ============================================================
# /CALCULATE
# ============================================================

@bot.tree.command(
    name="calculate",
    description="Calculate a basic arithmetic expression.",
)
@app_commands.describe(
    expression="Example: (25 * 4) + 10 / 2",
)
async def calculate(
    interaction: discord.Interaction,
    expression: str,
) -> None:
    try:
        result = safe_calculate(expression)

        # PUBLIC
        await interaction.response.send_message(
            f"🧮 `{expression}` = **{result}**",
            ephemeral=False,
        )

    except ValueError as exc:
        await interaction.response.send_message(
            f"❌ {exc}",
            ephemeral=False,
        )


# ============================================================
# /INFO
# ============================================================

@bot.tree.command(
    name="info",
    description="Show your configured crypto addresses.",
)
async def info(
    interaction: discord.Interaction,
) -> None:
    try:
        wallets = get_wallets(interaction.user.id)

    except Exception as exc:
        print("Supabase info error:", repr(exc))

        await interaction.response.send_message(
            "❌ Database error.",
            ephemeral=False,
        )
        return

    lines = []

    for coin, name in COINS.items():
        status = (
            "✅ Configured"
            if wallets.get(coin)
            else "❌ Not configured"
        )

        lines.append(
            f"**{name}:** {status}"
        )

    embed = discord.Embed(
        title="📋 Your Crypto Configuration",
        description="\n".join(lines),
    )

    embed.set_footer(
        text="Use /<coin> to view or configure a wallet."
    )

    # PUBLIC
    await interaction.response.send_message(
        embed=embed,
        ephemeral=False,
    )


# ============================================================
# /HELP
# ============================================================

@bot.tree.command(
    name="help",
    description="Show all available bot commands.",
)
async def help_command(
    interaction: discord.Interaction,
) -> None:
    embed = discord.Embed(
        title="🤖 Crypto Bot Help",
        description=(
            "**/checktx <txid>** — Check a transaction and open its explorer.\n\n"
            "**/ltc** — View or configure your Litecoin address.\n"
            "**/btc** — View or configure your Bitcoin address.\n"
            "**/eth** — View or configure your Ethereum address.\n"
            "**/sol** — View or configure your Solana address.\n"
            "**/usdt** — View or configure your USDT address.\n\n"
            "**/bnb /xrp /doge /trx /ton /ada** — Additional wallet commands.\n"
            "**/dot /avax /matic /pol /link /shib** — Additional wallet commands.\n\n"
            "**/upi** — Show UPI payment information.\n"
            "**/calculate <expression>** — Calculate basic arithmetic.\n"
            "**/info** — Show your wallet configuration.\n"
            "**/help** — Show this help menu."
        ),
    )

    # PUBLIC
    await interaction.response.send_message(
        embed=embed,
        ephemeral=False,
    )


# ============================================================
# EVENTS
# ============================================================

@bot.event
async def on_ready() -> None:
    print("=" * 60)
    print(f"Logged in as: {bot.user} ({bot.user.id})")

    try:
        synced = await bot.tree.sync()

        print(
            f"Application commands synced: {len(synced)}"
        )

        print(
            "Commands: "
            + ", ".join(
                f"/{command.name}"
                for command in synced
            )
        )

    except Exception as exc:
        print(
            "COMMAND SYNC FAILED:",
            repr(exc),
        )

        print(
            "Check that the Discord application has "
            "the applications.commands scope."
        )

    print("=" * 60)


@bot.event
async def on_disconnect() -> None:
    print(
        "Discord disconnected. "
        "discord.py will attempt to reconnect."
    )


# ============================================================
# START
# ============================================================

print("Starting Crypto Discord Bot...")
print(
    "Python version:",
    os.sys.version.split()[0],
)

# Start Render's HTTP health server first.
web_thread = threading.Thread(
    target=run_web_server,
    daemon=True,
)

web_thread.start()

try:
    bot.run(DISCORD_TOKEN)

except discord.LoginFailure as exc:
    raise RuntimeError(
        "Discord rejected DISCORD_TOKEN. "
        "Make sure the Render variable contains the Bot Token "
        "for this exact Discord application."
    ) from exc

except Exception as exc:
    print(
        "BOT CRASHED:",
        repr(exc),
    )
    raise
