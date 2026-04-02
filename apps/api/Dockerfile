FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system qcai && useradd --system --gid qcai --home-dir /app --no-create-home qcai
RUN mkdir -p /app/source-assets/update_data && chown -R qcai:qcai /app

COPY apps/api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=qcai:qcai apps/api/app ./app
COPY --chown=qcai:qcai transcripts ./source-assets/transcripts
COPY --chown=qcai:qcai ["Quantum Computing AI Research Synthesis 2026.docx", "Analyzing Quantum Computing and AI Paper 2025.docx", "Quantum Computing and Artificial Intelligence Industry Use Cases.docx", "Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx", "Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence_Models.docx", "Intermediate_Quantum_Programming_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx", "Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx", "Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx", "./source-assets/"]
COPY --chown=qcai:qcai ["Quantum Computing and Artificial Intelligence 2025.mp4", "Quantum Computing and Artificial Intelligence 2026.mp4", "Industry Use Cases.mp4", "Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4", "The Hardware-First Imperative in Quantum Machine LearningHardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence_Models.mp4", "Intermediate_Quantum_Programming_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4", "Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4", "Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4", "./source-assets/"]
COPY --chown=qcai:qcai ["update_data/Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.docx", "update_data/Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.mp4", "update_data/Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.docx", "update_data/Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.mp4", "update_data/Module4_Expressive Bottlenecks Compression, Language, and Explanation.docx", "update_data/Module4_Expressive Bottlenecks Compression, Language, and Explanation.mp4", "update_data/Module6_From Algorithmic Novelty to Sustainable Hybrid Systems.docx", "update_data/Module6_From Algorithmic Novelty to Sustainable Hybrid Systems.mp4", "./source-assets/update_data/"]

USER qcai

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
