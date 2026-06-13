from routes.gallery_routes import _comfyui_output_images, _comfyui_prompt_metadata


def _history_entry():
    return {
        "prompt": [
            0,
            "prompt-id",
            {
                "1": {
                    "inputs": {"unet_name": "ideogram4.safetensors"},
                    "class_type": "UNETLoader",
                    "_meta": {"title": "Load Diffusion Model"},
                },
                "2": {
                    "inputs": {"high_level_description": "A detailed test prompt"},
                    "class_type": "PromptNode",
                    "_meta": {"title": "Positive Prompt"},
                },
            },
        ],
        "status": {"status_str": "success"},
        "outputs": {
            "3": {
                "images": [
                    {"filename": "preview.png", "type": "temp", "subfolder": ""},
                    {"filename": "final.png", "type": "output", "subfolder": ""},
                ]
            }
        },
    }


def test_comfyui_prompt_metadata_extracts_prompt_and_model():
    prompt, model = _comfyui_prompt_metadata(_history_entry())

    assert prompt == "A detailed test prompt"
    assert model == "ideogram4.safetensors"


def test_comfyui_output_images_only_returns_successful_saved_outputs():
    history = {
        "ok": _history_entry(),
        "failed": {
            "status": {"status_str": "error"},
            "outputs": {"1": {"images": [{"filename": "bad.png", "type": "output"}]}},
        },
    }

    outputs = list(_comfyui_output_images(history))

    assert len(outputs) == 1
    assert outputs[0][0] == "ok"
    assert outputs[0][1]["filename"] == "final.png"
