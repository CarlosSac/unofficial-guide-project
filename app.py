"""Generation and Gradio interface for The Unofficial Guide (Milestone 5).

Pipeline stage (see planning.md architecture diagram):
    query -> retrieve() -> build_context() -> Groq -> format_sources() -> Gradio

    python app.py    # starts the Gradio interface at http://localhost:7860

Two design rules enforced in code, not left to the LLM:
  1. The system prompt uses absolute language ("Answer ONLY", "do not use outside
     knowledge") so the model cannot rationalize around the grounding constraint.
  2. The source list is built from chunk metadata by _format_sources() and appended
     after the LLM call. Even if the model ignores sources entirely, attribution
     is always present in the output.
"""

import os

import gradio as gr
from dotenv import load_dotenv

import config
from retriever import retrieve

load_dotenv()

_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise SystemExit(
                "GROQ_API_KEY not found. Copy .env.example to .env and add your key."
            )
        from groq import Groq
        _client = Groq(api_key=api_key)
    return _client


_SYSTEM_PROMPT = """\
You are The Unofficial Guide, a student advisor for the Computer Science \
and Cybersecurity programs at the University of the District of Columbia (UDC).

Answer ONLY using the numbered context passages provided in the user message. \
Do not use outside knowledge, training data, or general facts about universities \
or degree programs.

Rules:
1. If the answer is not present in the context passages, respond with exactly: \
"I don't have that information in my sources."
2. Do not add a references or sources section to your answer. Source attribution \
is appended separately and automatically.
3. State facts directly. Do not hedge with phrases like "the context suggests" \
or "it appears that."
"""


def _build_context(chunks: list[dict]) -> str:
    """Number each retrieved chunk and label it with its source."""
    parts = []
    for i, chunk in enumerate(chunks, 1):
        source = chunk["metadata"].get("source", "Unknown")
        parts.append(f"[{i}] Source: {source}\n{chunk['text']}")
    return "\n\n".join(parts)


def generate_response(query: str, chunks: list[dict]) -> str:
    """Send the grounded prompt to Groq and return the answer text."""
    context = _build_context(chunks)
    user_message = f"Context:\n\n{context}\n\nQuestion: {query}"
    completion = _get_client().chat.completions.create(
        model=config.GROQ_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.0,
    )
    return completion.choices[0].message.content.strip()


def _format_sources(chunks: list[dict]) -> str:
    """Build a deduplicated source list from chunk metadata.

    Runs in Python after the LLM call so sources are always present
    regardless of whether the model mentioned them.
    """
    seen: set[str] = set()
    lines: list[str] = []
    for chunk in chunks:
        meta = chunk["metadata"]
        source = meta.get("source", "Unknown")
        doc_type = meta.get("doc_type", "")
        if source not in seen:
            seen.add(source)
            label = f"{source} ({doc_type})" if doc_type else source
            lines.append(f"- {label}")
    return "\n".join(lines)


def handle_query(question: str) -> str:
    """Full RAG pipeline: retrieve -> generate -> attach sources."""
    question = question.strip()
    if not question:
        return "Please enter a question."

    chunks = retrieve(question)
    answer_text = generate_response(question, chunks)
    sources = _format_sources(chunks)
    return f"{answer_text}\n\n**Sources consulted:**\n{sources}"


with gr.Blocks(title="The Unofficial Guide") as demo:
    gr.Markdown("# The Unofficial Guide")
    gr.Markdown(
        "Ask about courses, prerequisites, faculty, and student reviews "
        "for the UDC Computer Science and Cybersecurity programs. "
        "Answers are grounded in the source documents. If the information "
        "is not in the corpus, the system will say so."
    )

    inp = gr.Textbox(
        label="Your question",
        placeholder="e.g. What are the prerequisites for APCT 232?",
        lines=2,
    )
    btn = gr.Button("Ask", variant="primary")
    out = gr.Markdown()

    gr.Examples(
        examples=[
            ["What are the prerequisites for APCT 232 Computer Science II?"],
            ["Which textbook is used for APCT 110 Introduction to Programming?"],
            ["Which course covers reverse engineering and malware analysis?"],
            ["What do students say about Dr. Li Chen's teaching style?"],
            ["What is the difference between the BSCS and BS Cybersecurity programs?"],
        ],
        inputs=[inp],
    )

    btn.click(handle_query, inputs=[inp], outputs=[out])
    inp.submit(handle_query, inputs=[inp], outputs=[out])


if __name__ == "__main__":
    demo.launch()
