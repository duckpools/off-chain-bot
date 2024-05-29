```scala
{
	val optionUnitSize = 1L
	val minTxFee = 1000000L
	val optionExerciseRange = 480
	val repaymentAddress = fromBase58("GxqLnVQBqsnGNvWcxYA9y6YpRZzF7vfGzPnsTNWpvime")
	val poolNFT = fromBase58("FP5CYKh3YRLjduN4mjuGX9m9F8R9SavUL29AcrwBjTy6")
	val optionYAsset = fromBase58("2JkxeCABNHjWuGaujrDidiCq6i2iic9ofxT9U7WyMhuZ")
 
	val optionBox = SELF
	val optionScript = optionBox.propositionBytes
	val optionValue = optionBox.value
	val K = optionBox.R4[Long].get // Strike Price
	val t = optionBox.R5[Long].get // Expiry Block 
	val userPK = optionBox.R6[GroupElement].get
	
	val isBeforeExpiry = HEIGHT < t
	val isExercisable = HEIGHT >= t && HEIGHT <= t + optionExerciseRange
	val isUnExercised = HEIGHT > t + optionExerciseRange

	if (isBeforeExpiry) {
		proveDlog(userPK) && sigmaProp(
			INPUTS(0).tokens(0)._1 == poolNFT &&
			INPUTS(0).tokens(3)._1 == SELF.tokens(0)._1 &&
			INPUTS(0).tokens(3)._2 + 1 == OUTPUTS(0).tokens(3)._2 
		)
	} else if (isExercisable) {
		val optionSize = optionValue - 1000000L
		val repayment = OUTPUTS(0)
		val repaymentScript = repayment.propositionBytes
		val repaymentValue = repayment.value
		val repaymentOptionToken = repayment.tokens(0)
		val repaymetYAsset = repayment.tokens(1)
		val repaymentId = repayment.R4[Coll[Byte]].get
		
		val isValidRepaymentScript = sigmaProp(repaymentScript) == repaymentAddress
		val isValidRepaymentValue = repaymentValue >=  2 * minTxFee
		val isOptionTokenSupplied = repaymentOptionToken == SELF.tokens(0)
		val isValidYAmount = repaymetYAsset._2.toBigInt >= repaymetYAsset._2.toBigInt + (optionSize.toBigInt * K.toBigInt) / optionUnitSize.toBigInt 
		val isValidYAsset = repaymetYAsset._1 == optionYAsset
		val isValidId = repaymentId == SELF.id
		
		
		proveDlog(userPK) && sigmaProp(
			isValidRepaymentScript &&
			isValidRepaymentValue &&
			isValidYAmount &&
			isOptionTokenSupplied &&
			isValidYAsset &&
			isValidId
		)
	} else {
		val repayment = OUTPUTS(0)
		val repaymentScript = repayment.propositionBytes
		val repaymentValue = repayment.value
		val repaymentOptionToken = repayment.tokens(0)
		val repaymentId = repayment.R4[Coll[Byte]].get
		
		val isValidRepaymentScript = sigmaProp(repaymentScript) == repaymentAddress
		val isValidRepaymentValue = repaymentValue >= SELF.value - minTxFee
		val isValidId = repaymentId == SELF.id
		val isOptionTokenSupplied = repaymentOptionToken == SELF.tokens(0)

		sigmaProp(
			isValidRepaymentScript &&
			isValidRepaymentValue &&
			isValidId &&
			isOptionTokenSupplied 
		)
	}

}
```