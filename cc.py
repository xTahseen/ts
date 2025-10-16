import os
import asyncio
from PIL import Image
from pyrogram import Client, filters, enums
from utils.misc import modules_help, prefix
from utils.scripts import format_exc, import_library
from utils.config import gemini_key

genai = import_library("google.genai", "google-genai")
client = genai.Client(api_key=gemini_key)

MODEL_NAME = "gemini-2.5-flash"
COOK_GEN_CONFIG = {
    "temperature": 0.35, "top_p": 0.95, "top_k": 40, "max_output_tokens": 1024
}

def _valid_file(reply, file_type=None):
    if file_type == "image":
        return getattr(reply, "photo", None) is not None
    if file_type in {"audio", "video"}:
        return any(getattr(reply, attr, False) for attr in ("audio", "voice", "video", "video_note"))
    return (
        getattr(reply, "photo", None)
        or getattr(reply, "audio", None)
        or getattr(reply, "voice", None)
        or getattr(reply, "video", None)
        or getattr(reply, "video_note", None)
        or getattr(reply, "document", None)
    )

async def _upload_file(file_path, file_type):
    uploaded = await asyncio.to_thread(client.files.upload, file=file_path)
    for _ in range(120):
        state = getattr(uploaded, "state", None)
        name = getattr(uploaded, "name", None) or getattr(uploaded, "id", None)
        if state and getattr(state, "name", "").upper() == "ACTIVE":
            return uploaded
        if state and getattr(state, "name", "").upper() == "FAILED":
            raise ValueError(f"{file_type.capitalize()} failed to process")
        if name:
            try:
                uploaded = await asyncio.to_thread(client.files.get, name=name)
            except Exception:
                pass
        await asyncio.sleep(1)
    raise ValueError(f"{file_type.capitalize()} upload timed out")

async def prepare_input_data(reply, file_path, prompt):
    if reply.photo:
        with Image.open(file_path) as img:
            img.verify()
        return [prompt, await _upload_file(file_path, "image")]
    if reply.video or reply.video_note:
        return [prompt, await _upload_file(file_path, "video")]
    if reply.audio or reply.voice:
        return [await _upload_file(file_path, "audio"), prompt]
    if reply.document and file_path.endswith(".pdf"):
        return [prompt, await _upload_file(file_path, "PDF")]
    if reply.document:
        return [await _upload_file(file_path, "document"), prompt]
    raise ValueError("Unsupported file type")

async def ai_process_handler(message, prompt, show_prompt=False, cook_mode=False, expect_type=None, status_msg="Processing..."):
    reply = message.reply_to_message
    if not reply:
        usage_hint = f"<b>Usage:</b> <code>{prefix}{message.command[0]} [prompt]</code> [Reply to a file]" if expect_type is None else \
            f"<b>Usage:</b> <code>{prefix}{message.command[0]} [custom prompt]</code> [Reply to a {expect_type}]"
        return await message.edit_text(usage_hint)
    if not _valid_file(reply, file_type=expect_type):
        type_text = expect_type if expect_type else "supported"
        return await message.edit_text(f"<code>Invalid {type_text} file. Please try again.</code>")
    await message.edit_text(f"<code>{status_msg}</code>")
    file_path = await reply.download()
    if not file_path or not os.path.exists(file_path):
        return await message.edit_text("<code>Failed to process the file. Try again.</code>")

    uploaded_file = None
    try:
        input_data = await prepare_input_data(reply, file_path, prompt)
        if len(input_data) > 1 and hasattr(input_data[1], "name"):
            uploaded_file = input_data[1]

        for _ in range(3):
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=MODEL_NAME,
                    contents=input_data,
                    config=COOK_GEN_CONFIG if cook_mode else None
                )
                break
            except Exception as e:
                msg = str(e).lower()
                if "mimetype parameter" in msg and "not supported" in msg:
                    if expect_type is None:
                        return await message.edit_text("<code>Invalid file type. Please try again.</code>")
                    else:
                        raise
                if any(x in msg for x in ("403", "429", "permission", "quota")):
                    await asyncio.sleep(2)
                else:
                    raise
        else:
            raise e

        text_out = getattr(response, "text", None)
        if not text_out:
            try:
                text_out = response.candidates[0].content[0].text
            except Exception:
                text_out = None

        result_text = (f"**Prompt:** {prompt}\n" if show_prompt else "") + f"**Answer:** {text_out or '<code>No content generated.</code>'}"
        if len(result_text) > 4000:
            for i in range(0, len(result_text), 4000):
                await message.reply_text(result_text[i:i+4000], parse_mode=enums.ParseMode.MARKDOWN)
            await message.delete()
        else:
            await message.edit_text(result_text, parse_mode=enums.ParseMode.MARKDOWN)
    except ValueError as e:
        await message.edit_text(f"<code>{str(e)}</code>")
    except Exception as e:
        await message.edit_text(f"<code>Error:</code> {format_exc(e)}")
    finally:
        if uploaded_file:
            try:
                await asyncio.to_thread(client.files.delete, name=getattr(uploaded_file, "name", getattr(uploaded_file, "id", None)))
            except Exception:
                pass
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass

@Client.on_message(filters.command("getai", prefix) & filters.me)
async def getai(_, message):
    prompt = (
        message.text.split(maxsplit=1)[1]
        if len(message.command) > 1
        else "Get details of the image, be accurate as much possible, write short response."
    )
    await ai_process_handler(
        message, prompt, show_prompt=len(message.command) > 1,
        expect_type="image", status_msg="Scanning...")

@Client.on_message(filters.command("aicook", prefix) & filters.me)
async def aicook(_, message):
    await ai_process_handler(
        message,
        "Identify the baked good in the image and provide an accurate recipe.",
        cook_mode=True, expect_type="image", status_msg="Cooking...")

@Client.on_message(filters.command("aiseller", prefix) & filters.me)
async def aiseller(_, message):
    if len(message.command) > 1:
        target_audience = message.text.split(maxsplit=1)[1]
        prompt = f"Generate a marketing description for the product.\nTarget Audience: {target_audience}"
        await ai_process_handler(message, prompt, expect_type="image", status_msg="Generating description...")
    else:
        await message.edit_text(
            f"<b>Usage:</b> <code>{prefix}aiseller [target audience]</code> [Reply to a product image]"
        )

@Client.on_message(filters.command(["transcribe", "ts"], prefix) & filters.me)
async def transcribe(_, message):
    prompt = (
        message.text.split(maxsplit=1)[1]
        if len(message.command) > 1
        else "Transcribe it. write only transcription text."
    )
    await ai_process_handler(
        message, prompt, show_prompt=len(message.command) > 1,
        expect_type="audio", status_msg="Transcribing...")

@Client.on_message(filters.command(["process", "pr"], prefix) & filters.me)
async def pr_command(_, message):
    args = message.text.split(maxsplit=1)
    show_prompt = len(args) > 1
    prompt = args[1] if show_prompt else "Shortly summarize the content of file details of the file."
    await ai_process_handler(message, prompt, show_prompt=show_prompt)

modules_help["generative"] = {
    "getai [custom prompt] [reply to image]*": "Analyze an image using AI.",
    "aicook [reply to image]*": "Identify food and generate cooking instructions.",
    "aiseller [target audience] [reply to image]*": "Generate marketing descriptions for products.",
    "transcribe [custom prompt] [reply to audio/video]*": "Transcribe or summarize an audio or video file.",
    "process [prompt] [reply to any file]*": "Process any file (image, audio, video, PDF, document, code, etc).",
}
