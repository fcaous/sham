import os
import ast
import operator as op
import threading
from datetime import datetime, timezone

from flask import Flask
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from supabase import create_client

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
    "?ex=6ab8d53f&is=6ab783bf&hm=0c2bdffd612a1fb72cb62393465329c41c19583847c5c2d3f4b67f6876c58948&=&format=webp"
)

for name, value in {
    "DISCORD_TOKEN": DISCORD_TOKEN,
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_KEY": SUPABASE_KEY,
}.items():
    if not value:
        raise RuntimeError(
            f"{name} is missing from Render environment variables."
        )

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY,
)

# ============================================================
# RENDER WEB SERVICE
# ============================================================

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
        debug=False,
        use_reloader=False,
    )


# ============================================================
# COINS
# ============================================================

COINS = {
    "btc": "Bitcoin",
    "ltc": "Litecoin",
    "eth": "Ethereum",
    "sol": "Solana",
    "usdt": "USDT",
    "bnb": "BNB",
    "xrp": "XRP",
    "doge": "Dogecoin",
    "trx": "TRON",
    "ton": "TON",
    "ada": "Cardano",
    "dot": "Polkadot",
    "avax": "Avalanche",
    "matic": "Polygon",
    "pol": "POL",
    "link": "Chainlink",
    "shib": "Shiba Inu",
}

# ============================================================
# DISCORD
# ============================================================

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
)

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
)

bot.tree.allowed_contexts = app_commands.AppCommandContext(
    guild=True,
    dm_channel=True,
    private_channel=True,
)

bot.tree.allowed_installs = app_commands.AppInstallationType(
    guild=True,
    user=True,
)


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

    return {}


def save_wallet(
    user_id: int,
    coin: str,
    address: str,
):
    existing = get_wallets(user_id)

    now = datetime.now(
        timezone.utc
    ).isoformat()

    if existing.get("id"):
        (
            supabase
            .table("wallets")
            .update({
                coin: address,
                "updated_at": now,
            })
            .eq(
                "user_id",
                str(user_id),
            )
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
# WALLET CONFIGURATION
# ============================================================

class WalletModal(discord.ui.Modal):

    def __init__(self, coin: str):
        super().__init__(
            title=f"Configure {COINS[coin]}"
        )

        self.coin = coin

        self.address_input = discord.ui.TextInput(
            label=f"{COINS[coin]} address",
            placeholder="Paste your wallet address here",
            required=True,
            min_length=8,
            max_length=256,
        )

        self.add_item(
            self.address_input
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):
        address = self.address_input.value.strip()

        try:
            save_wallet(
                interaction.user.id,
                self.coin,
                address,
            )

            await interaction.response.send_message(
                f"Your **{COINS[self.coin]}** address has been saved.",
                ephemeral=True,
            )

        except Exception as exc:
            print(
                "Supabase save error:",
                repr(exc),
            )

            await interaction.response.send_message(
                "I couldn't save the address. "
                "Check your Supabase table/configuration.",
                ephemeral=True,
            )


class ConfigureView(discord.ui.View):

    def __init__(self, coin: str):
        super().__init__(
            timeout=300
        )

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
    ):
        await interaction.response.send_modal(
            WalletModal(self.coin)
        )


async def show_wallet(
    interaction: discord.Interaction,
    coin: str,
):
    try:
        wallets = get_wallets(
            interaction.user.id
        )

        address = wallets.get(coin)

    except Exception as exc:
        print(
            "Supabase read error:",
            repr(exc),
        )

        await interaction.response.send_message(
            "Database error. Check your Supabase configuration.",
            ephemeral=True,
        )

        return

    # Not configured = private configuration button.
    if not address:

        await interaction.response.send_message(
            f"Your **{COINS[coin]}** address is not configured yet.",
            view=ConfigureView(coin),
            ephemeral=True,
        )

        return

    embed = discord.Embed(
        title=f"{COINS[coin]} Address",
        description=f"`{address}`",
    )

    embed.set_footer(
        text="Make sure you use the correct network."
    )

    # Configured address = PUBLIC.
    await interaction.response.send_message(
        embed=embed,
        ephemeral=False,
    )


def make_wallet_callback(
    coin: str,
):

    async def callback(
        interaction: discord.Interaction,
    ):
        await show_wallet(
            interaction,
            coin,
        )

    return callback


# Register wallet commands.
for coin, name in COINS.items():

    bot.tree.add_command(
        app_commands.Command(
            name=coin,
            description=f"Show or configure your {name} address.",
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
    txid="Transaction hash / ID",
    network="Blockchain network",
)
@app_commands.choices(
    network=[
        app_commands.Choice(
            name="Bitcoin",
            value="btc",
        ),
        app_commands.Choice(
            name="Litecoin",
            value="ltc",
        ),
        app_commands.Choice(
            name="Ethereum",
            value="eth",
        ),
        app_commands.Choice(
            name="Solana",
            value="sol",
        ),
        app_commands.Choice(
            name="BNB Chain",
            value="bnb",
        ),
        app_commands.Choice(
            name="TRON",
            value="trx",
        ),
    ]
)
async def checktx(
    interaction: discord.Interaction,
    txid: str,
    network: app_commands.Choice[str],
):

    txid = txid.strip()

    if not txid:

        await interaction.response.send_message(
            "Enter a transaction ID.",
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
            f"[Open transaction explorer]"
            f"({explorers[network.value]})"
        ),
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=False,
    )


# ============================================================
# /UPI
# ============================================================

@bot.tree.command(
    name="upi",
    description="Show the UPI payment image.",
)
async def upi(
    interaction: discord.Interaction,
):

    embed = discord.Embed(
        title="UPI Payment",
        description="Use the payment information below.",
    )

    embed.set_image(
        url=UPI_IMAGE_URL
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=False,
    )


# ============================================================
# CALCULATOR
# ============================================================

BINARY_OPS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.FloorDiv: op.floordiv,
    ast.Mod: op.mod,
    ast.Pow: op.pow,
}

UNARY_OPS = {
    ast.UAdd: op.pos,
    ast.USub: op.neg,
}


def safe_calculate(
    expression: str,
):

    expression = expression.strip()

    if not expression:
        raise ValueError(
            "Enter a calculation."
        )

    if len(expression) > 100:
        raise ValueError(
            "Calculation is too long."
        )

    try:
        tree = ast.parse(
            expression,
            mode="eval",
        )

    except SyntaxError:
        raise ValueError(
            "Invalid calculation."
        )

    def evaluate(node):

        if isinstance(
            node,
            ast.Expression,
        ):
            return evaluate(
                node.body
            )

        if (
            isinstance(
                node,
                ast.Constant,
            )
            and isinstance(
                node.value,
                (int, float),
            )
        ):

            if abs(node.value) > 10**100:
                raise ValueError(
                    "Number is too large."
                )

            return node.value

        if (
            isinstance(
                node,
                ast.BinOp,
            )
            and type(node.op) in BINARY_OPS
        ):

            left = evaluate(
                node.left
            )

            right = evaluate(
                node.right
            )

            if (
                isinstance(
                    node.op,
                    ast.Pow,
                )
                and abs(right) > 100
            ):
                raise ValueError(
                    "Exponent is too large."
                )

            try:
                result = BINARY_OPS[
                    type(node.op)
                ](
                    left,
                    right,
                )

            except ZeroDivisionError:
                raise ValueError(
                    "Cannot divide by zero."
                )

            return result

        if (
            isinstance(
                node,
                ast.UnaryOp,
            )
            and type(node.op) in UNARY_OPS
        ):
            return UNARY_OPS[
                type(node.op)
            ](
                evaluate(
                    node.operand
                )
            )

        raise ValueError(
            "Only basic arithmetic is supported."
        )

    return evaluate(tree)


@bot.tree.command(
    name="calculate",
    description="Calculate a mathematical expression.",
)
@app_commands.describe(
    expression="Example: (25 * 4) + 10 / 2",
)
async def calculate(
    interaction: discord.Interaction,
    expression: str,
):

    try:

        result = safe_calculate(
            expression
        )

        await interaction.response.send_message(
            f"`{expression}` = **{result}**",
            ephemeral=False,
        )

    except (
        ValueError,
        TypeError,
        OverflowError,
    ) as exc:

        await interaction.response.send_message(
            f"Error: {exc}",
            ephemeral=False,
        )


# ============================================================
# /INFO
# ============================================================

@bot.tree.command(
    name="info",
    description="Show all configured wallet statuses.",
)
async def info(
    interaction: discord.Interaction,
):

    try:
        wallets = get_wallets(
            interaction.user.id
        )

    except Exception as exc:

        print(
            "Supabase info error:",
            repr(exc),
        )

        await interaction.response.send_message(
            "Database error.",
            ephemeral=True,
        )

        return

    lines = []

    for coin, name in COINS.items():

        if wallets.get(coin):

            lines.append(
                f"🟢 **{name}:** Configured"
            )

        else:

            lines.append(
                f"🔴 **{name}:** Not configured"
            )

    embed = discord.Embed(
        title="Wallet Configuration",
        description="\n".join(lines),
    )

    embed.set_footer(
        text="Use /coin to view or configure an address."
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=False,
    )


# ============================================================
# /HELP
# ============================================================

@bot.tree.command(
    name="help",
    description="Show what each command does.",
)
async def help_command(
    interaction: discord.Interaction,
):

    embed = discord.Embed(
        title="Crypto Bot Commands",
        description=(
            "**/checktx** — Check a blockchain transaction.\n"
            "**/btc** — Show/configure Bitcoin address.\n"
            "**/ltc** — Show/configure Litecoin address.\n"
            "**/eth** — Show/configure Ethereum address.\n"
            "**/sol** — Show/configure Solana address.\n"
            "**/usdt** — Show/configure USDT address.\n"
            "**/bnb** — Show/configure BNB address.\n"
            "**/xrp** — Show/configure XRP address.\n"
            "**/doge** — Show/configure Dogecoin address.\n"
            "**/trx** — Show/configure TRON address.\n"
            "**/ton** — Show/configure TON address.\n"
            "**/ada** — Show/configure Cardano address.\n"
            "**/dot** — Show/configure Polkadot address.\n"
            "**/avax** — Show/configure Avalanche address.\n"
            "**/matic** — Show/configure Polygon address.\n"
            "**/pol** — Show/configure POL address.\n"
            "**/link** — Show/configure Chainlink address.\n"
            "**/shib** — Show/configure Shiba Inu address.\n"
            "**/upi** — Show the UPI payment image.\n"
            "**/calculate** — Calculate arithmetic.\n"
            "**/info** — Show wallet configuration status.\n"
            "**/help** — Show this help."
        ),
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=False,
    )


# ============================================================
# AUTOMATIC COMMAND REGISTRATION
# ============================================================

@bot.event
async def setup_hook():

    try:

        await bot.tree.sync()

        print(
            "Slash commands registered successfully."
        )

    except Exception as exc:

        print(
            "Slash command registration failed:",
            repr(exc),
        )


@bot.event
async def on_ready():

    print(
        f"Logged in as {bot.user} ({bot.user.id})"
    )

    print(
        "Discord connection is ready."
    )


# ============================================================
# START
# ============================================================

print(
    "Starting Crypto Discord Bot..."
)

print(
    "Python:",
    os.sys.version.split()[0],
)

threading.Thread(
    target=run_web_server,
    daemon=True,
).start()

bot.run(
    DISCORD_TOKEN
)
