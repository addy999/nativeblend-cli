# NativeBlend CLI

Open-source command-line interface for building 3D models in Blender using AI.

## Features

- 🎨 **Text & Image to 3D** - Build models from natural language descriptions
- ⚡ **Local Blender Execution** - Fast rendering on your machine, no bandwidth waste
- 🔄 **Real-time Progress** - Live streaming updates from the AI agent
- 🎯 **Multiple Quality Modes** - Express, Standard, and Pro build modes
- 🔐 **Secure** - API keys stored in system keychain

## Installation

```bash
pip install nativeblend
```

Or install from source:

```bash
git clone https://github.com/addy999/nativeblend-cli.git
cd nativeblend-cli
uv sync
alias nativeblend="uv run nativeblend --"
```

Then use `nativeblend` command in your terminal.

## Quick Start

Make sure you have Python and Blender installed on your machine.

1. Initialize the CLI:

```bash
nativeblend init
```

2. Get your API key from [nativeblend](https://nativeblend.app)

3. Configure your API key:

```bash
nativeblend auth login
# Enter your API key when prompted
```

4. Build your first model:

```bash
nativeblend build "a low poly spaceship"
```

## Usage

### Build a 3D Model

```bash
# Basic build
nativeblend build "a red cube"

# Use different quality modes
nativeblend build "a spaceship" --mode pro

# Use a reference image
nativeblend build "a car" --image reference.jpg

# Use a specific style
nativeblend build "a car" --style low-poly
nativeblend build "a racing car" --mode pro --style realistic
nativeblend build "a spaceship" --image reference.jpg --style cartoon

# Enable verbose output
nativeblend build "a tree" --verbose
```

### Modes

- **express** - Fast build, single iteration (<10min)
- **standard** - Balanced quality with refinement (<30min)
- **pro** - High quality with multiple refinement passes (<60min)

### Styles

Use `--style` to control the visual aesthetic of your model:

- **auto** - Let the AI decide based on your prompt (default)
- **low-poly** - Flat-shaded faceted polygons, hard edges, bold solid colors — classic indie game asset style
- **semi-realistic** - Blend of realism and stylization
- **realistic** - Detailed, lifelike appearance
- **cartoon** - Smooth, rounded cartoon look
- **geometric** - Clean, hard-edged geometric forms
- **voxel** - Minecraft-like block-based style
- **retro** - Classic retro/pixel-art inspired
- **pixel-art** - picoCAD/PICO-8 style: low-poly flat-shaded geometry with unlit solid colors from the 16-color PICO-8 palette

### Change output dir

By default renders and outputs are saved to `./outputs`. Change this in your config:

```bash
nativeblend config set output.default_dir /path/to/outputs
```

### Authentication

```bash
# Login with API key
nativeblend auth login

# Check authentication status
nativeblend auth status

# Logout
nativeblend auth logout
```

## How It Works

1. **CLI sends prompt** - Your prompt is sent to NativeBlend's cloud API
2. **AI builds code** - NativeBlend creates Blender Python scripts
3. **Inline execution** - Blender tasks (rendering, exporting) run locally on your machine during the build stream
4. **Iterative refinement** - NativeBlend reviews renders and improves until perfect

Your Blender installation stays local - only prompts and small preview images are sent to the cloud. No background workers needed; everything runs inline in your terminal.

## Configuration

Configuration file location: `~/.config/nativeblend/config.toml`

```toml
[api]
endpoint = "https://blender-ai.fly.dev"
timeout = 300

[blender]
executable = "/Applications/Blender.app/Contents/MacOS/Blender"  # macOS
# executable = "/usr/bin/blender"  # Linux
# executable = "C:\\Program Files\\Blender Foundation\\Blender\\blender.exe"  # Windows

[output]
default_dir = "./outputs"
save_renders = true
```

## Requirements

- Python 3.12 or higher
- Blender 4.5 or higher installed locally
- NativeBlend API key

## Pricing

- **Free Tier**: 5 builds/month (express or standard mode)
- **Indie**: $29/month - Unlimited builds (express + standard + pro)
- **Team**: $79/month - Unlimited builds + 3 seats + team collaboration features

See [pricing](https://nativeblend.app) for details.

## Troubleshooting

### Blender Not Found

If you get "Blender executable not found":

```bash
# Set blender path explicitly
nativeblend config set blender.executable /path/to/blender
```

## Development

```bash
# Clone the repository
git clone https://github.com/addy999/nativeblend-cli.git
cd nativeblend-cli

# Install development dependencies
uv sync

# Format code
black src/
ruff check src/
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## Support

- 📖 Documentation (coming soon)
- 💬 [Discord Community](https://discord.gg/CKKuWpfCCu)
- 🐛 [Issue Tracker](https://github.com/addy999/nativeblend-cli/issues)
- 📧 Email: support@nativeblend.app

## Powered By

NativeBlend CLI is powered by NativeBlend's proprietary AI agent infrastructure, combining industry knowledge with advanced vision models for iterative 3D builds.

---

Made with ❤️ by the NativeBlend team
