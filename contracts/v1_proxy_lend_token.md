```scala
{
	val minTxFee      = 1000000L
	val minBoxValue   = 1000000L
	
	val user          = SELF.R4[Coll[Byte]].get
	val requestAmount = SELF.R5[Long].get
	val publicRefund  = SELF.R6[Long].get
	val lendPoolToken = SELF.R7[Coll[Byte]].get
	val poolNFT = SELF.R8[Coll[Byte]].get
	val feeGiven = SELF.R9[Long].get
	
	sigmaProp(if (OUTPUTS.size < 3) {
		val refundBox = OUTPUTS(0)
		val deltaErg = SELF.value - refundBox.value
		val validDeltaErg = deltaErg <= minTxFee
		val validRefundScript = refundBox.propositionBytes == user
		val validHeight = HEIGHT >= publicRefund
		val multiBoxRefund = if (refundBox.R4[Coll[Byte]].isDefined) refundBox.R4[Coll[Byte]].get == SELF.id else false
		val validTokens = if(refundBox.tokens.size != 0) refundBox.tokens(0) == SELF.tokens(0) else false

		val refund = (
			validRefundScript &&
			validDeltaErg &&
			multiBoxRefund &&
			validHeight &&
			validTokens
		)
		refund
	} else {
		val MaxLendTokens = 9000000000000010L
		val MaxBorrowTokens = 9000000000000000L
		val inputPool = INPUTS(0)
		val outputPool = OUTPUTS(0)
		
		val isValidPool = inputPool.tokens(0)._1 == outputPool.tokens(0)._1 && outputPool.tokens(0)._1 == poolNFT
		
		// Current pool values
		val currentLendTokens = inputPool.tokens(1)
		val currentBorrowTokens = inputPool.tokens(2)
		val currentPooledTokens = inputPool.tokens(3)
		val currentLendTokensCirculating = MaxLendTokens - currentLendTokens._2.toBigInt
		val currentTotalBorrowed = MaxBorrowTokens - currentBorrowTokens._2.toBigInt
		val currentPooledAssets = currentPooledTokens._2.toBigInt

		// Successor pool values
		val successorLendTokens = outputPool.tokens(1)
		val successorBorrowTokens = outputPool.tokens(2)
		val successorPooledTokens = outputPool.tokens(3)
		val successorLendTokensCirculating = MaxLendTokens - successorLendTokens._2.toBigInt
		val successorTotalBorrowed = MaxBorrowTokens - successorBorrowTokens._2.toBigInt
		val successorPooledAssets = successorPooledTokens._2.toBigInt

		val isValidSuccessorLendTokensCirculating = successorLendTokensCirculating + 2 >=
			(successorPooledAssets + successorTotalBorrowed) * currentLendTokensCirculating / 
			((currentPooledAssets + currentTotalBorrowed)) 
		
		val amountToUser = successorLendTokensCirculating - currentLendTokensCirculating
		val amountDepositedValid = successorPooledAssets - currentPooledAssets == SELF.tokens(0)._2 - feeGiven
		
		val successor = OUTPUTS(2)
		val exchangedTokens = successor.tokens
		
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