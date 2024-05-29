```scala
{
	// Constants
	val transactionFee = 1000000L 
	val PoolNft = fromBase58("FP5CYKh3YRLjduN4mjuGX9m9F8R9SavUL29AcrwBjTy6") // Non-fungible token for the pool
	
	val initalPool = INPUTS(0)
	val finalPool = OUTPUTS(0)
	
	val validFinalPool = finalPool.tokens(0)._1 == PoolNft
	val validInitialPool = initalPool.tokens(0)._1 == PoolNft
	
	
	val isOptionTokensIncreasing = finalPool.tokens(3)._2 == initalPool.tokens(3)._2 + 1
	
	val deltaValue = finalPool.value - initalPool.value
	
	val validValue = deltaValue >= SELF.value - transactionFee
	val isAssetYValid = if (SELF.tokens.size > 1) {
			finalPool.tokens(2)._2 == initalPool.tokens(2)._2 + SELF.tokens(1)._2
	} else {
		true
	}
	
	// Check that SELF is INPUTS(1) to prevent same box attack
	val multiBoxSpendSafety = INPUTS(1) == SELF
	
	// Combine all the conditions into a single Sigma proposition
	sigmaProp(
		validFinalPool &&
		validInitialPool &&
		isOptionTokensIncreasing &&
		validValue &&
		multiBoxSpendSafety 
	)
}
```