# Agentic AI Warranty Claims Processor

This repository contains an **agentic AI system** for processing warranty claims for a consumer electronics company that sells multiple hair dryer products. Each product has its own warranty policy, coverage rules, and exclusions.

The system automates the intake, analysis, and decision support for warranty claim emails while keeping a **human reviewer in the loop**. It is designed to be **explainable, policy-grounded, and safe for production extension**.

---

## What the System Does

For each incoming email-based claim, the system performs the following steps:

1. **Triage**  
   Classifies incoming emails as either warranty claims or non-claims (spam or irrelevant messages).

2. **Extraction**  
   Extracts structured information from unstructured email text, including product name, purchase date, issue description, and proof of purchase.

3. **Policy Selection**  
   Identifies the correct warranty policy based on the extracted product information.

4. **Decision Support**  
   Applies deterministic, policy-grounded logic to recommend one of the following:
   - Approve the claim  
   - Reject the claim  
   - Request more information  

5. **Human Review**  
   A human reviewer reviews the recommendation and makes the final decision via the terminal.

6. **Customer Response**  
   Drafts customer-facing emails and generates return shipping labels if the claim is approved and sufficient information is available.

---

## Architecture Overview

The system is implemented as a **single agent orchestrating multiple specialized tools**:

- Inbox Tool – Reads file-based incoming emails  
- Triage Tool – Determines whether an email is a warranty claim or not  
- Extraction Tool – Converts unstructured text into structured claim data  
- Policy Retriever – Selects the relevant warranty policy and extracts key sections  
- Decision Tool – Applies deterministic, policy-grounded logic  
- Email Writer – Drafts customer communication  
- Label Generator – Creates mock return shipping labels  
- Orchestrator – Coordinates the end-to-end workflow  
- CLI Interface – Enables human-in-the-loop interaction  

A visual architecture diagram is included in the repository:

## Project Structure

```text
warranty-claims-processor/ 
├── README.md                         # Project overview and setup instructions
├── requirements.txt                  # Python dependencies
├── architecture_diagram_fixed.svg    # System architecture diagram
├── src/
│   ├── main.py                       # CLI entry point
│   ├── orchestrator.py               # Workflow orchestration logic
│   ├── schemas.py                    # Shared data models
│   └── tools/
│       ├── inbox_tool.py             # File-based inbox reader
│       ├── triage_tool.py            # Claim vs non-claim classification
│       ├── extraction_tool.py        # Structured claim extraction
│       ├── policy_retriever.py       # Policy selection & retrieval
│       ├── decision_tool.py          # Policy-grounded decision logic
│       ├── email_writer.py           # Customer email drafting
│       └── label_generator.py        # Return label generation
├── data/
│   ├── inbox/                        # Sample incoming claim emails
│   ├── policies/                     # Warranty policy documents
│   ├── review_queue/                 # Generated human review packets (runtime)
│   ├── decisions/                    # Human decisions (runtime)
│   ├── outbox/                       # Draft emails and labels (runtime)
│   └── triage_rejected/              # Non-claim emails (runtime)
└── report/
    └── report.pdf                     # Design & evaluation report
```

## Setup Instructions (Fresh Machine)

1. **Clone the Repository**

        git clone https://github.com/raksh-dev/Warranty-Claims-Processor.git 
        cd Warranty-Claims-Processor

2. **Required Directory Setup**

    Some output directories are intentionally not committed to the repository because they are generated at runtime and may be empty on a fresh clone.

    Before running the demo, create the following directories inside the data/ folder:

     - data/review_queue/

     - data/decisions/

     - data/outbox/

     - data/triage_rejected/

    Create directories manually

        You may create these folders using your file explorer or terminal.

    Create directories using terminal

    macOS / Linux

            mkdir -p data/review_queue data/decisions data/outbox data/triage_rejected


    Windows (PowerShell)

            mkdir data\review_queue, data\decisions, data\outbox, data\triage_rejected


    Once these directories are created, the system will write all generated outputs to the appropriate locations during execution.

3. **Create and Activate a Virtual Environment**

    macOS / Linux

        python3 -m venv venv
        source venv/bin/activate

    Windows (PowerShell)

        python -m venv venv
        .\venv\Scripts\Activate.ps1

4. **Install Dependencies**

        pip install --upgrade pip
        pip install -r requirements.txt

## Environment Variables (LLM Access)

The system supports OpenAI, Anthropic, or a heuristic-only fallback.

Create a .env file in the project root.

OpenAI 

        OPENAI_API_KEY=your_api_key 
        OPENAI_MODEL=gpt-4o-mini

Anthropic 

        ANTHROPIC_API_KEY=your_api_key 
        ANTHROPIC_MODEL=claude-3-5-sonnet-latest


Notes:

 - .env is excluded from version control

 - No secrets are committed to the repository

 - If no API key is provided, the system runs using deterministic heuristics only

## Running the Demo (One Command)

From the project root directory, run:

        python -m src.main demo


This command:

 - Processes all sample emails in data/inbox/

 - Displays human review prompts in the terminal

 - Writes outputs to:

    - data/review_queue/

    - data/decisions/

    - data/outbox/

    - data/triage_rejected/

## Human-in-the-Loop Interaction

For each claim, the terminal displays a summary and prompts the reviewer to choose one of the following actions:

 - A – Approve

 - R – Reject

 - M – Request more information

Based on the human decision, the system:

 - Drafts customer emails

 - Generates return shipping labels (if approved and address is available)

 - Requests missing information when required

## Sample Inputs and Outputs
### Inputs

 - Sample claim emails are located in data/inbox/

 - Warranty policy documents are located in data/policies/

### Outputs

After running the demo:

 - Human review packets → data/review_queue/*.json

 - Human decisions → data/decisions/*.json

 - Customer emails → data/outbox/*.txt

 - Return labels → data/outbox/*.txt

 - Rejected non-claim emails → data/triage_rejected/

## Evaluation & Reporting

A detailed design and evaluation report is included at:

        report/report.md

The report covers:

 - Problem framing and assumptions

 - System design and agent roles

 - Policy selection and decision rationale

 - Human-in-the-loop workflow

 - Evaluation plan and sample results

 - Future improvements

 - Intentional limitations and trade-offs


## Final Notes

This project prioritizes correctness, explainability, and human oversight over full automation. It demonstrates how agentic AI can safely support complex, policy-driven workflows in real-world operational settings.
