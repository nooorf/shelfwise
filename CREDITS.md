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
| Qwen3-8B, Qwen3-14B (via Ollama, GPU runs only) | Book tags, grounding runs | [Qwen](https://huggingface.co/Qwen) | Apache-2.0 |
| ms-marco-MiniLM-L6-v2 | Cross-encoder reranker | [cross-encoder](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2) | Apache-2.0 |
| bge-reranker-base | Cross-encoder reranker | [BAAI](https://huggingface.co/BAAI/bge-reranker-base) | MIT |

Fonts and covers in the web app, installed with its npm packages or loaded in the browser:

| What | Used for | Source | Licence |
| --- | --- | --- | --- |
| Source Serif 4 (variable, optical sizes) | Display type on the landing page: headlines and the example request | [Adobe](https://github.com/adobe-fonts/source-serif), via [@fontsource-variable/source-serif-4](https://fontsource.org/fonts/source-serif-4) | SIL Open Font License 1.1 |
| Schibsted Grotesk (variable) | Text on the landing page | [The Schibsted-Grotesk Project Authors](https://github.com/schibsted/schibsted-grotesk), via [@fontsource-variable/schibsted-grotesk](https://fontsource.org/fonts/schibsted-grotesk) | SIL Open Font License 1.1 |
| Open Library covers | Book covers on the shelf, cards and drawer, loaded by the browser | [Open Library Covers API](https://openlibrary.org/dev/docs/api/covers) | Covers belong to their publishers; shown as catalogue thumbnails under Open Library's terms |

Data, downloaded or looked up by the `make` targets, never committed:

| What | Used for | Source | Licence |
| --- | --- | --- | --- |
| UCSD Book Graph (Goodreads, 2017) | The bulk of the catalog: ~5,000 works, descriptions, shelves as genres | [UCSD McAuley lab](https://mcauleylab.ucsd.edu/public_datasets/gdrive/goodreads/UCSD%20Book%20Graph.html) | Academic use only; not redistributed. Cite Wan & McAuley, RecSys 2018; Wan et al., ACL 2019 |
| Open Library | The seed shelf's edition and work metadata | [openlibrary.org](https://openlibrary.org/developers/licensing) | CC0 |
