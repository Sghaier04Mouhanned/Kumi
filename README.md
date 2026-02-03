# SchedAI: Automated Class Schedule Extraction

SchedAI is a Python project that extracts structured class schedule information from documents such as PDFs or images using OCR and LLMs. The pipeline converts raw schedules into validated JSON, making it easy to analyze, display, or integrate into other systems.

---

## Features

- Extract schedule information from multiple files in a folder
- Supports PDF and image input
- Uses **OCR / DPT models** to read text from documents
- Leverages **Llama-3 (via Hugging Face or Groq)** for structured JSON extraction
- Validates output using **Pydantic**
- Flexible: supports multiple schedules, instructors, and class types


