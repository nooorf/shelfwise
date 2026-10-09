# Credits

Third-party models and assets Shelfwise uses at runtime. None of the files below are in this
repository; the `make download-*` targets fetch them.

| What | Used for | Source | Licence |
| --- | --- | --- | --- |
| Kokoro-82M v1.0 (int8 ONNX), voice `af_heart` | Text-to-speech | [hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M), ONNX export by [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) | Apache-2.0 (model), MIT (kokoro-onnx) |
| Silero VAD v6.2.3 | Finding where a spoken question starts and ends | [snakers4/silero-vad](https://github.com/snakers4/silero-vad) | MIT |
| Whisper large-v3-turbo (MLX, 4-bit) | Speech-to-text on Apple Silicon | [openai/whisper](https://github.com/openai/whisper), MLX conversion by [mlx-community](https://huggingface.co/mlx-community/whisper-large-v3-turbo-q4) | MIT |
| VRM1_Constraint_Twist_Sample | Placeholder avatar until our own VRoid model | © 2022 pixiv Inc., [vrm-c/vrm-specification samples](https://github.com/vrm-c/vrm-specification/tree/master/samples/VRM1_Constraint_Twist_Sample) | [VRM Public License 1.0](https://vrm.dev/licenses/1.0/): avatar use by anyone, commercial use, modification and redistribution allowed, credit not required |
| bge-base-en-v1.5 | Book and query embeddings | [BAAI](https://huggingface.co/BAAI/bge-base-en-v1.5) | MIT |
| Qwen3-4B (via Ollama) | Query parsing and narration | [Qwen](https://huggingface.co/Qwen/Qwen3-4B) | Apache-2.0 |
