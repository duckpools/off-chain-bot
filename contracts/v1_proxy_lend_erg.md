```scala
{
	val minTxFee      = 1000000L
	val minBoxValue   = 1000000L
	
	val user          = SELF.R4[Coll[Byte]].get
	val requestAmount = SELF.R5[Long].get
	val publicRefund  = SELF.R6[Long].get
	val lendPoolToken = SELF.R7[Coll[Byte]].get
	val poolNFT = SELF.R8[Coll[Byte]].get
	val feesGiven = SELF.R9[Long].get
	
	
	sigmaProp(if (OUTPUTS.size < 3) {
		val refundBox = OUTPUTS(0)
		val deltaErg = SELF.value - refundBox.value
		val validDeltaErg = deltaErg <= minTxFee
		val validRefundScript = refundBox.propositionBytes == user
		val validHeight = HEIGHT >= publicRefund
		val multiBoxRefund = if (refundBox.R4[Coll[Byte]].isDefined) refundBox.R4[Coll[Byte]].get == SELF.id else false
		val refund = (
			validRefundScript &&
			validDeltaErg &&
			multiBoxRefund &&
			validHeight
		)
		refund
	} else {
		val MaxLendTokens = 9000000001000000L
		val MaxBorrowTokens = 9000000000000000L		
		val successor = OUTPUTS(2)
		val exchangedTokens = successor.tokens

		val inputPool = INPUTS(0)
		val outputPool = OUTPUTS(0)
		
		val isValidPool = inputPool.tokens(0)._1 == outputPool.tokens(0)._1 && outputPool.tokens(0)._1 == poolNFT
		
		// Current pool values
		val currentLendTokens = inputPool.tokens(1)
		val currentBorrowTokens = inputPool.tokens(2)
		val currentPooledAssets = inputPool.value.toBigInt
		val currentLendTokensCirculating = MaxLendTokens - currentLendTokens._2.toBigInt
		val currentTotalBorrowed = MaxBorrowTokens - currentBorrowTokens._2.toBigInt

		// Successor pool values
		val successorLendTokens = outputPool.tokens(1)
		val successorBorrowTokens = outputPool.tokens(2)
		val successorPooledAssets = outputPool.value.toBigInt
		val successorLendTokensCirculating = MaxLendTokens - successorLendTokens._2.toBigInt
		val successorTotalBorrowed = MaxBorrowTokens - successorBorrowTokens._2.toBigInt

		val isValidSuccessorLendTokensCirculating = successorLendTokensCirculating + 2 >=
			(successorPooledAssets + successorTotalBorrowed) * currentLendTokensCirculating / 
			((currentPooledAssets + currentTotalBorrowed)) 
		
		val amountToUser = successorLendTokensCirculating - currentLendTokensCirculating
		val amountDepositedValid = successorPooledAssets - currentPooledAssets == SELF.value - feesGiven
		
		val validSuccessorScript = successor.propositionBytes == user
		val validTokens = if (exchangedTokens.size > 0){exchangedTokens(0)._1 == lendPoolToken && exchangedTokens(0)._2 >= amountToUser} else {false}
		val multiBoxSpendSafety = if (successor.R7[Coll[Byte]].isDefined) successor.R7[Coll[Byte]].get == SELF.id else false
		
		val exchange = (
			isValidPool &&
			isValidSuccessorLendTokensCirculating &&
			amountDepositedValid &&
			validSuccessorScript &&
			validTokens &&
			multiBoxSpendSafety
		)
		exchange
	})
}
```