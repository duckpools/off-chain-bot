# Autobalance ErgoScript

## Overview

This script enforces on-chain validation for autobalance transactions. It replaces the current `true` address with proper validation logic.

## Autobalance Box Structure

| Register/Field | Type | Description |
|----------------|------|-------------|
| Token[0] | Coll[Byte] | Spend NFT ID (matches collateral R8[:32]) |
| R4 | Coll[Byte] | Spend NFT ID (hex encoded) |
| R5 | Coll[Coll[Byte]] | Group special bytes (unordered) |
| R6 | Coll[Byte] | UserErgoTree |
| R7 | GroupElement | UserPk (for bypass path) |
| R9 | Coll[Coll[Byte]] | Ordered special bytes (R9[i] = bytes for INPUTS[i]) |

## Transaction Structure

```
INPUTS:  [collateral_0, collateral_1, autobalance_box, logic_0, logic_1]
OUTPUTS: [collateral_0, quote_0, collateral_1, quote_1, autobalance_box]
DATA INPUTS: [interest_box, primary_dex, secondary_dexes...]
```

## Collateral R8 Structure

- Bytes 0-31 (64 hex chars): Spend NFT ID (`iSpendingNFTShort`)
- Bytes 32-39 (16 hex chars): Special bytes (`iSpendingNFTEnd`) linking to group

## NFT Proof Mechanism

The collateral contract checks for NFT proof via:
```ergoscript
val nftProofGiven = INPUTS.filter{
    (b: Box) => b.tokens.size > 0 &&
                b.tokens(0)._1 == iSpendingNFTShort &&
                b.R9[Coll[Coll[Byte]]].get(selfIndex) == iSpendingNFTEnd
}.size > 0
```

## Spending Paths

### Path 1: UserPk Bypass
`proveDlog(R7[GroupElement])` allows full bypass of all conditions. This lets the user spend the autobalance box without restriction.

### Path 2: Autobalance Conditions
All of the following must be satisfied:
1. **Collateral Count**: Exactly 2 collateral inputs
2. **R9 Matching**: Each collateral's `R8[32:40]` matches `R9[inputIndex]`
3. **SpendNFT Matching**: Each collateral's `R8[:32]` matches `Token[0]`
4. **10% Imbalance**: `|quotePrice0 - quotePrice1| * 100 > 10 * min(price0, price1)`
5. **Value Preservation**: Output total >= input total - fees
6. **Midpoint Direction**: Higher value decreases, lower increases
7. **Borrow Tokens Preserved**: Output tokens(0) == input tokens(0)
8. **Box Recreation**: Autobalance box recreated with same Token[0] and R5

## ErgoScript

```ergoscript
{
    // Autobalance Box Script
    // This box authorizes rebalancing of collateral boxes in a group
    // when their quoted values differ by more than 10%
    //
    // Spending paths:
    // 1. UserPk bypass: proveDlog(R7) allows spending without any validation
    // 2. Autobalance: All validation conditions must pass

    // Constants - replace with actual values when compiling
    val CollateralContractScript = fromBase58("COLLATERAL_SCRIPT_HASH")
    val MinimumBoxValue = 1000000L
    val BalanceThresholdNumerator = 10L   // 10% threshold
    val BalanceThresholdDenominator = 100L
    val MaxTransactionFees = 5000000L  // 0.005 ERG max fee allowance

    // Autobalance box registers:
    // Token[0]: Spend NFT ID that collateral R8[:32] must match
    // R4: Spend NFT ID (hex encoded)
    // R5: Coll[Coll[Byte]] - List of special bytes for loans in this group (unordered)
    // R6: UserErgoTree
    // R7: GroupElement - UserPk for bypass path
    // R9: Coll[Coll[Byte]] - Ordered array where R9[i] = special bytes for collateral at INPUTS[i]

    val spendNftId = SELF.tokens(0)._1
    val groupSpecialBytes = SELF.R5[Coll[Coll[Byte]]].get
    val userPk = SELF.R7[GroupElement].get
    val orderedSpecialBytes = SELF.R9[Coll[Coll[Byte]]].get

    // Find collateral inputs by matching the collateral contract script
    val collateralInputs = INPUTS.filter {
        (b: Box) => blake2b256(b.propositionBytes) == CollateralContractScript
    }
    val numCollaterals = collateralInputs.size

    // Verify we have exactly 2 collaterals
    val hasValidCollateralCount = numCollaterals == 2

    // Get self index to determine where collaterals are positioned
    val selfIndex = INPUTS.indexOf(SELF, 0)

    // Verify all collateral inputs are before the autobalance box
    val collateralsBeforeSelf = collateralInputs.forall {
        (b: Box) => INPUTS.indexOf(b, 0) < selfIndex
    }

    // Verify each collateral's R8 structure matches our requirements
    // Uses R9 ordering only (no R5 membership check)
    val allCollateralsValid = collateralInputs.indices.forall { (i: Int) =>
        val collateral = collateralInputs(i)
        val collateralR8 = collateral.R8[Coll[Byte]].get
        val collateralSpendNft = collateralR8.slice(0, 32)
        val collateralSpecialBytes = collateralR8.slice(32, 40)
        val inputIndex = INPUTS.indexOf(collateral, 0)

        // Verify:
        // 1. The spend NFT in R8[:32] matches our Token[0]
        // 2. The special bytes in R8[32:40] match R9[inputIndex]
        val matchesSpendNft = collateralSpendNft == spendNftId
        val matchesOrderedBytes = orderedSpecialBytes(inputIndex) == collateralSpecialBytes

        matchesSpendNft && matchesOrderedBytes
    }

    // Get quote boxes to read prices
    // Quote boxes are at OUTPUTS[2*inputIndex + 1] for collateral at INPUTS[inputIndex]
    // Quote R4[1] contains the quotePrice
    val collateral0Index = INPUTS.indexOf(collateralInputs(0), 0)
    val collateral1Index = INPUTS.indexOf(collateralInputs(1), 0)

    val quoteBox0 = OUTPUTS(2 * collateral0Index + 1)
    val quoteBox1 = OUTPUTS(2 * collateral1Index + 1)

    val quoteReport0 = quoteBox0.R4[Coll[Long]].get
    val quoteReport1 = quoteBox1.R4[Coll[Long]].get

    val quotePrice0 = quoteReport0(1)
    val quotePrice1 = quoteReport1(1)

    // Check if the two prices differ by more than 10%
    // Condition: |price0 - price1| * 100 > 10 * min(price0, price1)
    val priceDiff = if (quotePrice0 > quotePrice1) quotePrice0 - quotePrice1 else quotePrice1 - quotePrice0
    val minPrice = if (quotePrice0 < quotePrice1) quotePrice0 else quotePrice1

    // priceDiff * BalanceThresholdDenominator > BalanceThresholdNumerator * minPrice
    val hasSufficientImbalance = priceDiff * BalanceThresholdDenominator > BalanceThresholdNumerator * minPrice

    // Verify output collaterals exist and maintain proper structure
    // Output collaterals are at OUTPUTS[2*inputIndex] for collateral at INPUTS[inputIndex]
    val outputCollateral0 = OUTPUTS(2 * collateral0Index)
    val outputCollateral1 = OUTPUTS(2 * collateral1Index)

    // Verify output collaterals have correct script
    val outputCollateralsValid = (
        blake2b256(outputCollateral0.propositionBytes) == CollateralContractScript &&
        blake2b256(outputCollateral1.propositionBytes) == CollateralContractScript
    )

    // Verify total value is preserved (minus reasonable fees)
    val inputTotalValue = collateralInputs(0).value + collateralInputs(1).value
    val outputTotalValue = outputCollateral0.value + outputCollateral1.value
    val valuesPreserved = outputTotalValue >= inputTotalValue - MaxTransactionFees

    // Verify outputs trend towards midpoint:
    // The higher-value input should have lower or equal value in output
    // The lower-value input should have higher or equal value in output
    val inputVal0 = collateralInputs(0).value
    val inputVal1 = collateralInputs(1).value
    val outVal0 = outputCollateral0.value
    val outVal1 = outputCollateral1.value

    // Calculate expected midpoint direction
    val outputsBalanced = if (inputVal0 >= inputVal1) {
        // Input 0 is higher, should decrease; Input 1 should increase
        outVal0 <= inputVal0 && outVal1 >= inputVal1
    } else {
        // Input 1 is higher, should decrease; Input 0 should increase
        outVal1 <= inputVal1 && outVal0 >= inputVal0
    }

    // Verify borrow tokens are preserved in each collateral
    val borrowTokensPreserved = (
        outputCollateral0.tokens(0) == collateralInputs(0).tokens(0) &&
        outputCollateral1.tokens(0) == collateralInputs(1).tokens(0)
    )

    // Verify autobalance box is recreated with same core properties
    val autobalanceOutputs = OUTPUTS.filter { (b: Box) =>
        b.propositionBytes == SELF.propositionBytes &&
        b.tokens.size > 0 &&
        b.tokens(0)._1 == spendNftId
    }

    val autobalanceRecreated = autobalanceOutputs.size == 1 && {
        val successor = autobalanceOutputs(0)
        val successorGroupBytes = successor.R5[Coll[Coll[Byte]]].get

        // Verify core properties are preserved
        successor.tokens(0) == SELF.tokens(0) &&
        successorGroupBytes == groupSpecialBytes &&
        successor.value >= MinimumBoxValue
    }

    // Autobalance conditions - all must be met
    val autobalanceConditions = (
        hasValidCollateralCount &&
        collateralsBeforeSelf &&
        allCollateralsValid &&
        hasSufficientImbalance &&
        outputCollateralsValid &&
        valuesPreserved &&
        outputsBalanced &&
        borrowTokensPreserved &&
        autobalanceRecreated
    )

    // Two spending paths:
    // 1. UserPk bypass - user can spend without any validation
    // 2. Autobalance conditions - all checks must pass
    sigmaProp(autobalanceConditions) || proveDlog(userPk)
}
```

## Python Generator Function

Add this to `contracts/quacks.py`:

```python
def generate_autobalance_script(collateralScript):
    """
    Generate the autobalance ErgoScript for rebalancing collateral boxes.

    Args:
        collateralScript: Base58 encoded hash of collateral contract script

    Returns:
        Compiled script address
    """
    return compile_script(f'''{{
    val CollateralContractScript = fromBase58("{collateralScript}")
    val MinimumBoxValue = 1000000L
    val BalanceThresholdNumerator = 10L
    val BalanceThresholdDenominator = 100L
    val MaxTransactionFees = 5000000L

    val spendNftId = SELF.tokens(0)._1
    val groupSpecialBytes = SELF.R5[Coll[Coll[Byte]]].get
    val userPk = SELF.R7[GroupElement].get
    val orderedSpecialBytes = SELF.R9[Coll[Coll[Byte]]].get

    val collateralInputs = INPUTS.filter {{
        (b: Box) => blake2b256(b.propositionBytes) == CollateralContractScript
    }}
    val numCollaterals = collateralInputs.size

    val hasValidCollateralCount = numCollaterals == 2

    val selfIndex = INPUTS.indexOf(SELF, 0)

    val collateralsBeforeSelf = collateralInputs.forall {{
        (b: Box) => INPUTS.indexOf(b, 0) < selfIndex
    }}

    val allCollateralsValid = collateralInputs.indices.forall {{ (i: Int) =>
        val collateral = collateralInputs(i)
        val collateralR8 = collateral.R8[Coll[Byte]].get
        val collateralSpendNft = collateralR8.slice(0, 32)
        val collateralSpecialBytes = collateralR8.slice(32, 40)
        val inputIndex = INPUTS.indexOf(collateral, 0)

        val matchesSpendNft = collateralSpendNft == spendNftId
        val matchesOrderedBytes = orderedSpecialBytes(inputIndex) == collateralSpecialBytes

        matchesSpendNft && matchesOrderedBytes
    }}

    val collateral0Index = INPUTS.indexOf(collateralInputs(0), 0)
    val collateral1Index = INPUTS.indexOf(collateralInputs(1), 0)

    val quoteBox0 = OUTPUTS(2 * collateral0Index + 1)
    val quoteBox1 = OUTPUTS(2 * collateral1Index + 1)

    val quoteReport0 = quoteBox0.R4[Coll[Long]].get
    val quoteReport1 = quoteBox1.R4[Coll[Long]].get

    val quotePrice0 = quoteReport0(1)
    val quotePrice1 = quoteReport1(1)

    val priceDiff = if (quotePrice0 > quotePrice1) quotePrice0 - quotePrice1 else quotePrice1 - quotePrice0
    val minPrice = if (quotePrice0 < quotePrice1) quotePrice0 else quotePrice1

    val hasSufficientImbalance = priceDiff * BalanceThresholdDenominator > BalanceThresholdNumerator * minPrice

    val outputCollateral0 = OUTPUTS(2 * collateral0Index)
    val outputCollateral1 = OUTPUTS(2 * collateral1Index)

    val outputCollateralsValid = (
        blake2b256(outputCollateral0.propositionBytes) == CollateralContractScript &&
        blake2b256(outputCollateral1.propositionBytes) == CollateralContractScript
    )

    val inputTotalValue = collateralInputs(0).value + collateralInputs(1).value
    val outputTotalValue = outputCollateral0.value + outputCollateral1.value
    val valuesPreserved = outputTotalValue >= inputTotalValue - MaxTransactionFees

    val inputVal0 = collateralInputs(0).value
    val inputVal1 = collateralInputs(1).value
    val outVal0 = outputCollateral0.value
    val outVal1 = outputCollateral1.value

    val outputsBalanced = if (inputVal0 >= inputVal1) {{
        outVal0 <= inputVal0 && outVal1 >= inputVal1
    }} else {{
        outVal1 <= inputVal1 && outVal0 >= inputVal0
    }}

    val borrowTokensPreserved = (
        outputCollateral0.tokens(0) == collateralInputs(0).tokens(0) &&
        outputCollateral1.tokens(0) == collateralInputs(1).tokens(0)
    )

    val autobalanceOutputs = OUTPUTS.filter {{ (b: Box) =>
        b.propositionBytes == SELF.propositionBytes &&
        b.tokens.size > 0 &&
        b.tokens(0)._1 == spendNftId
    }}

    val autobalanceRecreated = autobalanceOutputs.size == 1 && {{
        val successor = autobalanceOutputs(0)
        val successorGroupBytes = successor.R5[Coll[Coll[Byte]]].get

        successor.tokens(0) == SELF.tokens(0) &&
        successorGroupBytes == groupSpecialBytes &&
        successor.value >= MinimumBoxValue
    }}

    val autobalanceConditions = (
        hasValidCollateralCount &&
        collateralsBeforeSelf &&
        allCollateralsValid &&
        hasSufficientImbalance &&
        outputCollateralsValid &&
        valuesPreserved &&
        outputsBalanced &&
        borrowTokensPreserved &&
        autobalanceRecreated
    )

    sigmaProp(autobalanceConditions) || proveDlog(userPk)
}}''')
```

## Validation Summary

| Check | Description |
|-------|-------------|
| `hasValidCollateralCount` | Exactly 2 collateral boxes in inputs |
| `collateralsBeforeSelf` | All collaterals appear before autobalance box in INPUTS |
| `allCollateralsValid` | Each collateral's R8[:32] matches Token[0] and R8[32:40] matches R9[inputIndex] |
| `hasSufficientImbalance` | Quote prices differ by >10% |
| `outputCollateralsValid` | Output collaterals use correct contract script |
| `valuesPreserved` | Total ERG value preserved (minus fees) |
| `outputsBalanced` | Higher value decreases, lower value increases |
| `borrowTokensPreserved` | Borrow tokens unchanged in each collateral |
| `autobalanceRecreated` | Autobalance box recreated with same properties |

## UserPk Bypass

The `proveDlog(userPk)` path allows the user to spend the autobalance box without any validation. This is useful for:
- Updating R5 (adding/removing loans from group)
- Updating R9 (reordering for different transaction)
- Withdrawing the autobalance box entirely
- Emergency recovery

The userPk is stored in R7 as a GroupElement and verified via Schnorr signature.
