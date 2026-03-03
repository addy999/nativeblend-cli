#!/usr/bin/env python3
"""
Blender 3D Model Generator CLI

A command-line tool for generating 3D models using natural language prompts.
This tool uses an AI agent to create Blender Python scripts that generate 3D models.
"""

import typer

app = typer.Typer(
    name="nativeblend",
    help="Generate 3D models in Blender using natural language prompts",
    add_completion=True,
)


@app.callback()
def main():
    """Native Blend CLI - Generate 3D models in Blender using natural language prompts"""
    pass


@app.command("generate")
def generate():
    print("Generating...")


if __name__ == "__main__":
    app()
