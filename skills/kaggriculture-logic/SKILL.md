# Kaggriculture Risk-Aware Crop Planner Rules

This file summarizes the runtime rules implemented by the offline simulator.

## Operational Constraints

1. **Capital Allocation Limit:**
   - No approved action may spend more than 40% of the cash available at the start of that decision.
   - This is an upper limit, not a spending target; waiting and lower-cost actions are valid.
   
2. **Observation Before Action:**
   - The simulator updates weather, soil, and market observations before the policy chooses one action.

3. **Crop-Specific Market Spike Halt:**
   - When a crop's absolute block-to-block price change is greater than 15%, buying, planting, and selling that crop are paused.
   - A change of exactly 15% is allowed.

4. **Deterministic Resource Safety:**
   - Inventory, seed availability, crop maturity, soil suitability, and irrigation usefulness are checked in Python before state can change.
