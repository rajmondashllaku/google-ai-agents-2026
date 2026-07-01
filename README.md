# Kaggriculture Agent

This workspace contains the Kaggriculture autonomous agent logic using the `google.adk` framework.

## Assignment Setup Guide

1. Create a virtual environment and install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Run the main simulation engine:
   ```bash
   python src/main.py
   ```

## 5-Block Capital Trace

The agent adheres strictly to the $\le 40\%$ allocation rule per block. The expected execution trace is flawlessly simulated as follows:
- **Starting Capital**: $1,000.00
- **Block 1**: Budget $400.00 | Remaining $600.00
- **Block 2**: Budget $240.00 | Remaining $360.00
- **Block 3**: Budget $144.00 | Remaining $216.00
- **Block 4**: Budget $86.40 | Remaining $129.60
- **Block 5**: Budget $51.84 | Remaining $77.76
- **Final Capital**: $77.76
