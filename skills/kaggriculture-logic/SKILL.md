# Kaggriculture Agent Skill Specifications

This file defines the strict runtime rules and constraints that the Kaggriculture Agent must follow.

## Operational Constraints

1. **Capital Allocation Limit:**
   - The agent MUST NEVER allocate more than 40% of its total capital reserves in any single simulation block.
   
2. **Execution Priority Order:**
   - The agent MUST check the latest weather vector deltas and soil moisture data BEFORE performing any seed acquisition or planting operations.

3. **Market Spike Halt:**
   - The agent MUST pause execution and log a warning if a market asset price delta spike exceeds 15% in a single simulation step.
