```scala
{
	val minTxFee      = 1000000L
	val minBoxValue   = 1000000L
	
	val user          = SELF.R4[Coll[Byte]].get
	val requestAmount = SELF.R5[Long].get
	val publicRefund  = SELF.R6[Long].get
	val requestedToken = SELF.R7[Coll[Byte]].get
	val poolNFT = SELF.R8[Coll[Byte]].get
	val feeGiven = SELF.R9[Long].get

	sigmaProp(if (OUTPUTS.size < 3) {
		val refundSuccessor = OUTPUTS(0)
		val deltaErg = SELF.value - refundSuccessor.value
		
		val validRefundSuccessor = refundSuccessor.propositionBytes == user
		val validDeltaErg = deltaErg <= minTxFee
		val validHeight   = HEIGHT >= publicRefund
		val multiBoxSafetyRefund =  if (refundSuccessor.R4[Coll[Byte]].isDefined) refundSuccessor.R4[Coll[Byte]].get == SELF.id else false
		val validTokens = if(refundSuccessor.tokens.size != 0) refundSuccessor.tokens(0) == SELF.tokens(0) else false
	
		
		// Refund conditions
		val refund = (
			validRefundSuccessor &&
			validDeltaErg &&
			multiBoxSafetyRefund &&
			validHeight &&
			validTokens && true && true && true
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

		val isValidSuccessorLendTokensCirculating = successorPooledAssets - 3 <= (successorLendTokensCirculating * (currentPooledAssets + currentTotalBorrowed) / currentLendTokensCirculating) - successorTotalBorrowed
		
		val amountToUser = currentPooledAssets - successorPooledAssets - feeGiven
		val amountDepositedValid = currentLendTokensCirculating- successorLendTokensCirculating == SELF.tokens(0)._2


		// Withdrawal conditions
		val successor = OUTPUTS(2)
		
		val validSuccessorScript = successor.propositionBytes == user		
		val validTokens = successor.tokens(0)._2 >= amountToUser && successor.tokens(0)._1 == requestedToken
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