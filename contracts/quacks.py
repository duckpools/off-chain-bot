from helpers.node_calls import compile_script


def generate_pool_script(collateralContractScript, childBoxNft, parameterBoxNft, serviceFeeThresholds):
    return compile_script(f'''{{
	// Constants
	val CollateralContractScript = fromBase58("{collateralContractScript}")
	val ChildBoxNft = fromBase58("{childBoxNft}")
	val ParamaterBoxNft = fromBase58("{parameterBoxNft}")
	val MaxLendTokens = 9000000000000010L // Set 1,000,000 higher than true maximum so that genesis lend token value is 1.
	val MaxBorrowTokens = 900000000000000000L
	val BorrowTokenDenomination = 10000000000000000L.toBigInt
	val LiquidationThresholdDenomination = 1000
	val MinimumBoxValue = 1000000 // Absolute minimum value allowed for pool box.
	val MinimumTxFee = 1000000L
	val Slippage = 2
	val DexFeeDenom = 1000
	val sFeeStepOne = {serviceFeeThresholds[0]}L
	val sFeeStepTwo = {serviceFeeThresholds[1]}L
	val sFeeDivisorOne = 160
	val sFeeDivisorTwo = 200
	val sFeeDivisorThree = 250
	val LendTokenMultipler = 1000000000000000L.toBigInt
	val MaximumNetworkFee = 5000000
	val MinLoanValue = 50000000L
	val forcedLiquidationBuffer = 500000
	val defaultBuffer = 100000000L

	// Current pool values
	val currentScript = SELF.propositionBytes
	val currentPoolValue = SELF.value
	val currentPoolNft = SELF.tokens(0)
	val currentLendTokens = SELF.tokens(1)
	val currentBorrowTokens = SELF.tokens(2)
	val currentPooledTokens = SELF.tokens(3)
	val currentLendTokensCirculating = MaxLendTokens - currentLendTokens._2
	val currentBorrowTokensCirculating = MaxBorrowTokens - currentBorrowTokens._2
	val currentPooledAssets = currentPooledTokens._2

	// Successor pool values
	val successor = OUTPUTS(0)
	val successorScript = successor.propositionBytes
	val successorPoolValue = successor.value
	val successorPoolNft = successor.tokens(0)
	val successorLendTokens = successor.tokens(1)
	val successorBorrowTokens = successor.tokens(2)
	val successorPooledTokens = successor.tokens(3)
	val successorLendTokensCirculating = MaxLendTokens - successorLendTokens._2
	val successorBorrowTokensCirculating = MaxBorrowTokens - successorBorrowTokens._2
	val successorPooledAssets = successorPooledTokens._2

	// Validation conditions under all spending paths
	val isValidSuccessorScript = successorScript == currentScript
	val isPoolNftPreserved = successorPoolNft == currentPoolNft 
	val isValidLendTokenId = successorLendTokens._1 == currentLendTokens._1 // Not required when the stronger isLendTokensUnchanged replaces this validation.
	val isValidBorrowTokenId = successorBorrowTokens._1 == currentBorrowTokens._1 // Not required when the stronger isBorrowTokensUnchanged replaces this validation.
	val isValidMinValue = successorPoolValue >= MinimumBoxValue 
	val isPooledAssetPreserved = successorPooledTokens._1 == currentPooledTokens._1
	
	// Extract Values from Interest Box
	val interestBox = CONTEXT.dataInputs(0)
	val interestBoxNFT = interestBox.tokens(0)._1
	val isValidInterestBox = interestBoxNFT == ChildBoxNft
	val borrowTokenValue = interestBox.R5[BigInt].get
	val currentBorrowed = currentBorrowTokensCirculating.toBigInt * borrowTokenValue / 	BorrowTokenDenomination
	val successorBorrowed = successorBorrowTokensCirculating.toBigInt * borrowTokenValue / BorrowTokenDenomination

	// Calculate Lend Token valuation
	val currentLendTokenValue = LendTokenMultipler * (currentPooledAssets.toBigInt + currentBorrowed.toBigInt) / currentLendTokensCirculating.toBigInt
	val successorLendTokenValue = LendTokenMultipler * (successorPooledAssets.toBigInt + successorBorrowed.toBigInt) / successorLendTokensCirculating.toBigInt

	// Additional validation conditions specific to exchange operation
	val isLendTokenValueMaintained = successorLendTokenValue > currentLendTokenValue // Ensures the current value of an LP token has not decreased
	val isBorrowTokensUnchanged = successorBorrowTokens == currentBorrowTokens
	
	// Useful value to store
	val deltaAssetsInPool = successorPooledAssets - currentPooledAssets
	val absDeltaAssetsInPool = if (deltaAssetsInPool > 0) deltaAssetsInPool else deltaAssetsInPool * -1
	
	// Validate service fee
	val isValidServiceFee = if (CONTEXT.dataInputs.size > 1) {{
		// Extract values from service fee box
		val serviceFeeBox = OUTPUTS(1)
		val serviceFeeScript = serviceFeeBox.propositionBytes
		val serviceFeeValue = serviceFeeBox.value
		val serviceFeeTokens = serviceFeeBox.tokens(0)
		val serviceFeeAssets = serviceFeeTokens._2

		// Extract values form serviceParamBox
		val serviceParamBox = CONTEXT.dataInputs(1)
		val serviceParamNft = serviceParamBox.tokens(0)
		val paramServiceFeeScript = serviceParamBox.R8[Coll[Byte]].get

		// Calculate total service fee owed
		val totalServiceFee = if (absDeltaAssetsInPool <= sFeeStepOne) {{
			absDeltaAssetsInPool / sFeeDivisorOne
		}} else {{
			if (absDeltaAssetsInPool <= sFeeStepTwo) {{
				(absDeltaAssetsInPool - sFeeStepOne) / sFeeDivisorTwo +
				sFeeStepOne / sFeeDivisorOne
			}} else {{
				(absDeltaAssetsInPool - sFeeStepTwo - sFeeStepOne) / sFeeDivisorThree +
				sFeeStepTwo / sFeeDivisorTwo +
				sFeeStepOne / sFeeDivisorOne
			}}
		}}

		// Validate service fee box
		val validServiceScript = serviceFeeScript == paramServiceFeeScript
		val validServiceFeeValue = serviceFeeValue >= MinimumBoxValue
		val validServiceTokens = serviceFeeAssets >= max(totalServiceFee, 1L) && serviceFeeTokens._1 == currentPooledTokens._1

		// Validate serviceParamBox
		val isValidServiceParamBox = serviceParamNft._1 == ParamaterBoxNft

		// Apply validation conditions
		(
			validServiceScript &&
			validServiceFeeValue &&
			validServiceTokens &&
			isValidServiceParamBox
		)
	}} else {{
		false
	}}

	// Validate exchange operation
	val isValidExchange = (
		isValidSuccessorScript &&
		isPoolNftPreserved &&
		isValidLendTokenId &&
		isValidMinValue &&
		isBorrowTokensUnchanged &&
		isLendTokenValueMaintained &&
		isPooledAssetPreserved &&
		isValidServiceFee &&
		isValidInterestBox
	)

	// Allow for deposits
	val deltaTotalBorrowed = successorBorrowTokensCirculating - currentBorrowTokensCirculating
	val deltaReservedLendTokens = successorLendTokens._2 - currentLendTokens._2

	val isLendTokensUnchanged = successorLendTokens == currentLendTokens
	val isAssetsInPoolIncreasing = deltaAssetsInPool > 0
	val isDepositDeltaBorrowedValid = deltaTotalBorrowed < 0 // Enforces a deposit to add borrow tokens to the pool

	// Validate deposit operation
	val isValidDeposit = (
		isValidSuccessorScript &&
		isValidMinValue &&
		isPoolNftPreserved &&
		isLendTokensUnchanged &&
		isValidBorrowTokenId &&
		isAssetsInPoolIncreasing &&
		isPooledAssetPreserved &&
		isDepositDeltaBorrowedValid
	)

	// Check for loans
	if (CONTEXT.dataInputs.size > 2) {{
		// Load Collateral Box Values
		val collateralBox = OUTPUTS(1)
		val collateralScript = collateralBox.propositionBytes
		val collateralValue = collateralBox.value
		val collateralBorrowTokens = collateralBox.tokens(0)
		val isCollateralOwnerDefined = collateralBox.R4[Coll[Byte]].isDefined
		val collateralInterestIndexes = collateralBox.R5[(Int, Int)].get
		val collateralThresholdPenalty = collateralBox.R6[(Long, Long)].get
		val collateralDexNft = collateralBox.R7[Coll[Byte]].get
		val isUserPkDefined = collateralBox.R8[GroupElement].isDefined
		val forcedLiquidation = collateralBox.R9[(Long, Long)].get._1
		val bufferLiquidation = collateralBox.R9[(Long, Long)].get._2
		val loanAmount = collateralBorrowTokens._2.toBigInt * borrowTokenValue / BorrowTokenDenomination
		val collateralParentIndex = collateralInterestIndexes(0)
		val collateralChildIndex = collateralInterestIndexes(1)

		// Load Dex pool values
		val poolNativeCurrencyId = currentPooledTokens._1
		val dexBox = CONTEXT.dataInputs(1)
		val dexReservesErg = dexBox.value
		val dexNft = dexBox.tokens(0)
		val dexReservesToken = dexBox.tokens(2)
		val dexFee = dexBox.R4[Int].get

		// Load parameter box values
		val paramaterBox = CONTEXT.dataInputs(2)
		val paramaterNft = paramaterBox.tokens(0)
		val liquidationThresholds = paramaterBox.R4[Coll[Long]].get
		val collateralAssetIds = paramaterBox.R5[Coll[Coll[Byte]]].get
		val collateralDexNfts = paramaterBox.R6[Coll[Coll[Byte]]].get
		val liquidationPenalties = paramaterBox.R7[Coll[Long]].get

		// Get collateral settings from paramaterBox
		val indexOfParams = collateralDexNfts.indexOf(dexNft._1, 0)
		val expectedCollateralId = collateralAssetIds(indexOfParams)
		val liquidationThreshold = liquidationThresholds(indexOfParams)
		val liquidationPenalty = liquidationPenalties(indexOfParams)

		// Check sufficient collateral
		val inputAmount = collateralValue - MaximumNetworkFee.toBigInt
		val collateralMarketValue = (dexReservesToken._2.toBigInt * inputAmount.toBigInt * dexFee.toBigInt) /
			((dexReservesErg.toBigInt + (dexReservesErg.toBigInt * Slippage.toBigInt / 100.toBigInt)) * DexFeeDenom.toBigInt +
			(inputAmount.toBigInt * dexFee.toBigInt))

		val isCorrectCollateralAmount = collateralMarketValue >= loanAmount.toBigInt * liquidationThreshold.toBigInt / LiquidationThresholdDenomination.toBigInt

		// Check correct collateral box tokens
		val isValidCollateral = isCorrectCollateralAmount
		val isValidCollateralBorrowTokenId = collateralBorrowTokens._1 == currentBorrowTokens._1

		// Check if interest indexes, penalty array, asset ID, and DEX NFT are valid in collateralBox
		val isValidChildIndex = collateralChildIndex == 0
		val isValidParentIndex = collateralParentIndex == 0
		val isValidThresholdPenaltyArray = collateralThresholdPenalty == (liquidationThreshold, liquidationPenalty)
		val isValidDexNft = collateralDexNft == dexNft._1

		// Check forced liquidation height
		val isValidForcedLiquidation = forcedLiquidation > HEIGHT && forcedLiquidation < HEIGHT + forcedLiquidationBuffer
		val isValidLiquidationBuffer = bufferLiquidation == defaultBuffer

		// Validate Erg and token values in LendPool and collateralBox
		val isAssetAmountValid = deltaAssetsInPool * -1 == loanAmount
		val isTotalBorrowedValid = deltaTotalBorrowed == collateralBorrowTokens._2

		// Validate other loaded boxes
		val isValidCollateralContract = blake2b256(collateralScript) == CollateralContractScript
		val isValidCollateralValue = collateralValue >= MinLoanValue + MinimumBoxValue + MinimumTxFee // Ensure collateral value sufficient for safety

		// Ensure asset reduction occurs
		val isAssetsInPoolDecreasing = deltaAssetsInPool < 0

		val isValidParamaterBox = paramaterNft._1 == ParamaterBoxNft
		val isValidBaseToken = dexReservesToken._1 == poolNativeCurrencyId

		// Validate borrow operation
		val isValidBorrow = (
			isValidSuccessorScript &&
			isAssetAmountValid &&
			isAssetsInPoolDecreasing &&
			isValidMinValue &&
			isPoolNftPreserved &&
			isPooledAssetPreserved &&
			isLendTokensUnchanged &&
			isValidBorrowTokenId &&
			isTotalBorrowedValid &&
			isValidCollateralContract &&
			isValidCollateralValue &&
			isValidCollateral &&
			isValidCollateralBorrowTokenId &&
			isCollateralOwnerDefined &&
			isValidChildIndex &&
			isValidParentIndex &&
			isValidThresholdPenaltyArray &&
			isValidDexNft &&
			isUserPkDefined &&
			isValidForcedLiquidation &&
			isValidLiquidationBuffer &&
			isValidBaseToken &&
			isValidParamaterBox
		)
		sigmaProp(isValidBorrow)
	}} else {{
		sigmaProp(isValidDeposit || isValidExchange)
	}}
}}''')

def generate_collateral_script(repaymentScript, interestNft, poolCurrencyId):
    return compile_script(f'''{{
	// Constants
	val RepaymentContractScript = fromBase58("{repaymentScript}")
	val ChildInterestNft = fromBase58("{interestNft}")
	val PoolCurrencyId = fromBase58("{poolCurrencyId}")
	val BorrowTokenDenomination = 10000000000000000L.toBigInt

	val InterestRateDenom = 100000000L
	val MaximumNetworkFee = 5000000
	val DexLpTaxDenomination = 1000
	val LiquidationThresholdDenom = 1000
	val PenaltyDenom = 1000
	val MinimumTransactionFee = 1000000L
	val MinimumBoxValue = 1000000
	val Slippage = 2 // Divided by 100 to represent 2%
	val defaultBuffer = 100000000L

	// Extract variables from SELF
	val currentScript = SELF.propositionBytes
	val currentValue = SELF.value
	val currentBorrowTokens = SELF.tokens(0)
	val currentBorrower = SELF.R4[Coll[Byte]].get
	val currentIndexes = SELF.R5[(Int, Int)].get
	val currentThresholdPenalty = SELF.R6[(Long, Long)].get
	val currentDexNft = SELF.R7[Coll[Byte]].get
	val currentUserPk = SELF.R8[GroupElement].get
	val currentForcedLiquidation = SELF.R9[(Long, Long)].get._1
	val currentLiquidationBuffer = SELF.R9[(Long, Long)].get._2
	val loanAmount = currentBorrowTokens._2
	val parentIndex = currentIndexes(0)
	val childIndex = currentIndexes(1)
	val liquidationThreshold = currentThresholdPenalty(0)
	val liquidationPenalty = currentThresholdPenalty(1)

	// Extract values from interest box
	val interestBox = CONTEXT.dataInputs(0)
	val interestBoxNFT = interestBox.tokens(0)._1
	val isValidInterestBox = interestBoxNFT == ChildInterestNft
	val borrowTokenValue = interestBox.R5[BigInt].get

	val totalOwed = loanAmount.toBigInt * borrowTokenValue / BorrowTokenDenomination


	// Branch into collateral adjustments or repayment/ liquidation
	if(INPUTS(0) == SELF) {{
		// Branch for adjusting collateral levels
		// Get values from successor collateral box
		val successor = OUTPUTS(0)
		val successorScript = successor.propositionBytes
		val successorValue = successor.value
		val successorBorrowTokens = successor.tokens(0)
		val successorBorrower = successor.R4[Coll[Byte]].get
		val successorIndexes = successor.R5[(Int, Int)].get
		val successorThresholdPenalty = successor.R6[(Long, Long)].get
		val successorDexNft = successor.R7[Coll[Byte]].get
		val successorUserPk = successor.R8[GroupElement].get
		val successorForcedLiquidation = successor.R9[(Long, Long)].get._1
		val successorBufferLiquidation = successor.R9[(Long, Long)].get._2

		// Extract values from dexBox
		val dexBox = CONTEXT.dataInputs(1)
		val dexReservesErg = dexBox.value
		val dexNft = dexBox.tokens(0)
		val dexReservesToken = dexBox.tokens(2)._2
		val inputAmount = successorValue - MaximumNetworkFee.toBigInt
		val dexFee = dexBox.R4[Int].get
		val collateralValue = (dexReservesToken.toBigInt * inputAmount.toBigInt * dexFee.toBigInt) /
		((dexReservesErg.toBigInt + (dexReservesErg.toBigInt * Slippage.toBigInt / 100.toBigInt)) * DexLpTaxDenomination.toBigInt +
		(inputAmount.toBigInt * dexFee.toBigInt))

		// Validate dexBox
		val validDexBox = dexNft._1 == currentDexNft

		// Validate successor collateral box
		val validSuccessorScript = successorScript == currentScript
		val retainBorrowTokens = successorBorrowTokens == currentBorrowTokens
		val retainRegisters = (
			successorBorrower == currentBorrower &&
			successorIndexes == currentIndexes &&
			successorThresholdPenalty == currentThresholdPenalty &&
			successorDexNft == currentDexNft &&
			successorUserPk == currentUserPk &&
			successorForcedLiquidation == currentForcedLiquidation &&
			successorBufferLiquidation == currentLiquidationBuffer
		)
		// Check sufficient remaining collateral
		val isCorrectCollateralAmount = (
			collateralValue >= totalOwed.toBigInt * liquidationThreshold.toBigInt / LiquidationThresholdDenom.toBigInt &&
			successorValue >= 3 * MinimumBoxValue + MinimumTransactionFee
		)

		// Allow spending by user if validation conditions met
		proveDlog(currentUserPk) &&
		sigmaProp(
			validSuccessorScript &&
			isCorrectCollateralAmount &&
			retainBorrowTokens &&
			retainRegisters &&
			validDexBox &&
			isValidInterestBox
		)
	}} else if (INPUTS(1) == SELF) {{
		// Extract values from borrowerBox
		val borrowerBox = OUTPUTS(0) // In liquidations OUTPUTS(0) is assumed to be DEX box
		val borrowerScript = borrowerBox.propositionBytes
		val borrowerValue = borrowerBox.value

		// Extract values from repayment box
		val repaymentBox = OUTPUTS(1)
		val repaymentScript = repaymentBox.propositionBytes
		val repaymentValue = repaymentBox.value
		val repaymentBorrowTokens = repaymentBox.tokens(0)
		val repaymentLoanTokens = repaymentBox.tokens(1)

		// Validate borrower's box
		val validBorrowerScript = borrowerScript == currentBorrower
		val validBorrowerCollateral = borrowerValue >= currentValue - MinimumTransactionFee

		// Validate repayment
		val validRepaymentScript = blake2b256(repaymentScript) == RepaymentContractScript
		val validRepaymentValue = repaymentValue >= MinimumBoxValue + MinimumTransactionFee
		val validRepaymentLoanTokens = repaymentLoanTokens._1 == PoolCurrencyId && repaymentLoanTokens._2 > totalOwed
		val validRecordOfLoan = repaymentBorrowTokens == currentBorrowTokens

		// Check repayment conditions
		val repayment = (
			validBorrowerScript &&
			validBorrowerCollateral &&
			validRepaymentScript &&
			validRepaymentValue &&
			validRepaymentLoanTokens &&
			validRecordOfLoan &&
			isValidInterestBox
		)
		val collateralRecreationPaths = if (OUTPUTS(0).tokens.size >= 1 && INPUTS(0).tokens.size < 3) {{
			// Partial Repay
			// Extract values form successor
			val successor = OUTPUTS(0)
			val successorScript = successor.propositionBytes
			val successorValue = successor.value
			val successorBorrowTokens = successor.tokens(0)
			val successorBorrower = successor.R4[Coll[Byte]].get
			val successorIndexes = successor.R5[(Int, Int)].get
			val successorThresholdPenalty = successor.R6[(Long, Long)].get
			val successorDexNft = successor.R7[Coll[Byte]].get
			val successorUserPk = successor.R8[GroupElement].get
			val successorForcedLiquidation = successor.R9[(Long, Long)].get._1
			val successorBufferLiquidation = successor.R9[(Long, Long)].get._2

			// Extract values from dexBox
			val dexBox = CONTEXT.dataInputs(1)
			val dexReservesErg = dexBox.value
			val dexNft = dexBox.tokens(0)
			val dexReservesToken = dexBox.tokens(2)._2
			val inputAmount = successorValue - MaximumNetworkFee.toBigInt
			val dexFee = dexBox.R4[Int].get
			val collateralValue = (dexReservesToken.toBigInt * inputAmount.toBigInt * dexFee.toBigInt) /
			((dexReservesErg.toBigInt + (dexReservesErg.toBigInt * Slippage.toBigInt / 100.toBigInt)) * DexLpTaxDenomination.toBigInt +
			(inputAmount.toBigInt * dexFee.toBigInt))

			// Validate dexBox
			val validDexBox = dexNft._1 == currentDexNft

			val finalTotalOwed = successorBorrowTokens._2 * borrowTokenValue / BorrowTokenDenomination

			// Check sufficient collateral value to prevent double-spend attempts on partialRepayment
			val isSufficientCollateral = (
				collateralValue >= finalTotalOwed.toBigInt * liquidationThreshold.toBigInt / LiquidationThresholdDenom.toBigInt &&
				successorValue >= 3 * MinimumBoxValue + MinimumTransactionFee
			)

			// Calculate expected borrowTokens
			val repaymentMade = repaymentLoanTokens._2
			val expectedBorrowTokens = currentBorrowTokens._2.toBigInt - (repaymentMade.toBigInt * BorrowTokenDenomination.toBigInt / borrowTokenValue.toBigInt)
			val validRepayLoanTokenId = repaymentLoanTokens._1 == PoolCurrencyId

			// Validate successor values
			val validSuccessorScript = successorScript == currentScript
			val retainMinValue = successorValue >= currentValue
			val retainBorrowTokenId = successorBorrowTokens._1 == currentBorrowTokens._1
			val validBorrowTokens = successorBorrowTokens._2.toBigInt >= expectedBorrowTokens
			val retainRegisters = (
				successorBorrower == currentBorrower &&
				successorIndexes == currentIndexes &&
				successorThresholdPenalty == currentThresholdPenalty &&
				successorDexNft == currentDexNft &&
				successorUserPk == currentUserPk &&
				successorForcedLiquidation == currentForcedLiquidation
			)

			// Validate repayment
			val validPartialRecordOfLoan = (
				repaymentBorrowTokens._2 == currentBorrowTokens._2 - successorBorrowTokens._2  &&
				repaymentBorrowTokens._1 == currentBorrowTokens._1
				)

			if (successorBufferLiquidation == defaultBuffer) {{
				// Partial Repayment conditions
				// Apply validation conditions
				val retainBuffer = currentLiquidationBuffer == successorBufferLiquidation
				(
					validSuccessorScript &&
					retainMinValue &&
					retainBorrowTokenId &&
					validBorrowTokens &&
					retainRegisters &&
					retainBuffer &&
					validRepaymentScript &&
					validRepaymentValue &&
					validRepayLoanTokenId &&
					validPartialRecordOfLoan &&
					isSufficientCollateral &&
					validDexBox &&
					isValidInterestBox
				)
			}} else {{
				val retainTokens = successor.tokens == SELF.tokens
				val adjustBuffer = successorBufferLiquidation > HEIGHT && successorBufferLiquidation < HEIGHT + 5
				val sufficientValue = successor.value >= SELF.value - MinimumTransactionFee
				val isFirstIndication = currentLiquidationBuffer == defaultBuffer
				(
					!isSufficientCollateral &&
					validSuccessorScript &&
					sufficientValue &&
					retainTokens &&
					retainRegisters &&
					adjustBuffer &&
					isFirstIndication &&
					validDexBox &&
					isValidInterestBox
				)
			}}
		}} else {{
			false
		}}

		// Check liquidation conditions if DEX box INPUTS(0) (will have tokens.size == 3)
		val liquidation = if (INPUTS(0).tokens.size >= 3) {{
			// Extract values from dexBox
			val dexBox = INPUTS(0)
			val dexReservesErg = dexBox.value
			val dexReservesToken = dexBox.tokens(2)._2
			val inputAmount = currentValue - MaximumNetworkFee.toBigInt
			val dexFee = dexBox.R4[Int].get
			val collateralValue = (dexReservesToken.toBigInt * inputAmount.toBigInt * dexFee.toBigInt) /
			((dexReservesErg.toBigInt + (dexReservesErg.toBigInt * Slippage.toBigInt / 100.toBigInt)) * DexLpTaxDenomination.toBigInt +
			(inputAmount.toBigInt * dexFee.toBigInt))

			// Validate DEX box
			val validDexBox = dexBox.tokens(0)._1 == currentDexNft

			val liquidationAllowed = (
				(
					collateralValue <= totalOwed.toBigInt * liquidationThreshold.toBigInt / LiquidationThresholdDenom.toBigInt &&
					HEIGHT >= currentLiquidationBuffer
				) ||
				HEIGHT > currentForcedLiquidation
			)

			val repaymentAmount = repaymentLoanTokens._2
			val validRepayLoanTokenId = repaymentLoanTokens._1 == PoolCurrencyId

			// Apply penalty on repayment and borrower share
			val borrowerShare = ((collateralValue - totalOwed.toBigInt) * (PenaltyDenom.toBigInt - liquidationPenalty.toBigInt)) / PenaltyDenom.toBigInt
			val applyPenalty = if (borrowerShare < 1.toBigInt) {{
				repaymentAmount.toBigInt >= collateralValue
			}} else {{
				val validRepayment = repaymentAmount.toBigInt >= totalOwed.toBigInt + ((collateralValue - totalOwed.toBigInt) * liquidationPenalty.toBigInt / PenaltyDenom.toBigInt)
				val borrowBox = OUTPUTS(2)
				val validBorrowerShare = borrowBox.tokens(0)._2.toBigInt >= borrowerShare
				val validBorrowerShareId = borrowBox.tokens(0)._1 == PoolCurrencyId
				val validBorrowerAddress = borrowBox.propositionBytes == currentBorrower
				validRepayment && validBorrowerShare && validBorrowerAddress && validBorrowerShareId
			}}

			// Apply liquidation validations
			(
				liquidationAllowed &&
				validRepaymentScript &&
				validRepayLoanTokenId &&
				validRepaymentValue &&
				applyPenalty &&
				validRecordOfLoan &&
				validDexBox &&
				isValidInterestBox
			)
		}} else {{
			false
		}}
	sigmaProp(repayment || liquidation || collateralRecreationPaths)
	}}
	else {{
		sigmaProp(false)
	}}
}}''')

def generate_repayment_script(poolNFT):
    p2s = f"""{{
	// Constants
	val transactionFee = 1000000L 
	val MaxBorrowTokens = 900000000000000000L // Maximum allowed borrowable tokens
	val PoolNft = fromBase58("{poolNFT}") // Non-fungible token for the pool
	
	val initalPool = INPUTS(0)
	val finalPool = OUTPUTS(0)
	
	// Amount borrowed
	val loanAmount = SELF.tokens(0)._2
	val repaymentTokens = SELF.tokens(1)
	val repaymentAmount = repaymentTokens._2
	
	// Find change in the pools borrow tokens
	val borrow0 = MaxBorrowTokens - initalPool.tokens(2)._2
	val borrow1 = MaxBorrowTokens - finalPool.tokens(2)._2	
	val deltaBorrowed = borrow0 - borrow1
	
	val assetsInPool0 = initalPool.tokens(3)._2
	val assetsInPool1 = finalPool.tokens(3)._2
	val deltaPoolAssets = assetsInPool1 - assetsInPool0
	
	// Check if the pool NFT matches in both initial and final state
	val validFinalPool = finalPool.tokens(0)._1 == PoolNft
	val validInitialPool = initalPool.tokens(0)._1 == PoolNft
	
	// Calculate the change in the value of the pool
	val deltaValue = finalPool.value - initalPool.value
	
	// Check if the delta value is greater than or equal to the loan amount minus the transaction fee
	val validValue = deltaValue >= SELF.value - transactionFee
	// Check if the delta between borrowed amounts is equal to the loan amount
	val validBorrowed = deltaBorrowed == loanAmount
	// Check repayment assets go to pull
	val validRepayment = repaymentAmount == deltaPoolAssets && repaymentTokens._1 == initalPool.tokens(3)._1
	
	// Check that SELF is INPUTS(1) to prevent same box attack
	val multiBoxSpendSafety = INPUTS(1) == SELF
	
	// Combine all the conditions into a single Sigma proposition
	sigmaProp(
		validFinalPool &&
		validInitialPool &&
		validValue &&
		validRepayment &&
		validBorrowed &&
		multiBoxSpendSafety
	)
}}"""
    return compile_script(p2s)

def generate_interest_script(poolNFT, interestParamNFT):
    return compile_script(f'''{{
	val PoolNft = fromBase58("{poolNFT}")
	val InterestParamaterBoxNft = fromBase58("{interestParamNFT}")
	val InterestDenomination = 100000000L
	val BorrowTokenDenomination = 10000000000000000L
	val CoefficientDenomination = 100000000L
	val InitiallyLockedLP = 9000000000000000L
	val MaximumBorrowTokens = 900000000000000000L
	val MaximumExecutionFee = 2000000
	val updateFrequency = 120

	val successor = OUTPUTS(0)
	val pool = CONTEXT.dataInputs(0)
	val parameterBox = CONTEXT.dataInputs(1)

	val recordedHeight = SELF.R4[Long].get
	val recordedValue = SELF.R5[BigInt].get
	
	val finalHeight = successor.R4[Long].get
	val finalValue = successor.R5[BigInt].get

	// get coefficients
	val coefficients = parameterBox.R4[Coll[Long]].get
	val a = coefficients(0).toBigInt
	val b = coefficients(1).toBigInt
	val c = coefficients(2).toBigInt
	val d = coefficients(3).toBigInt
	val e = coefficients(4).toBigInt
	val f = coefficients(5).toBigInt
	 
	val isReadyToUpdate = HEIGHT >= recordedHeight 

	val poolAssets = pool.tokens(3)._2
	val validFinalHeight = finalHeight == recordedHeight + updateFrequency
	
	val borrowTokens = MaximumBorrowTokens - pool.tokens(2)._2
	val borrowed = borrowTokens * recordedValue / BorrowTokenDenomination
	val util = (InterestDenomination.toBigInt * borrowed.toBigInt / (poolAssets.toBigInt + borrowed.toBigInt))

	val D = CoefficientDenomination.toBigInt
	val M = InterestDenomination.toBigInt
	val x = util.toBigInt

	val currentRate = (
		M + (
			a + 
			(b * x) / D + 
			(c * x) / D * x / M +
			(d * x) / D * x / M * x / M +
			(e * x) / D * x / M * x / M * x / M + 
			(f * x) / D * x / M * x / M * x / M * x / M
			)
		) 

	val retainedERG = successor.value >= SELF.value - MaximumExecutionFee
	val preservedInterestNFT = successor.tokens == SELF.tokens

	val validSuccessorScript = SELF.propositionBytes == successor.propositionBytes
	val validValueUpdate = finalValue == recordedValue * currentRate / M

	val validPoolBox = pool.tokens(0)._1 == PoolNft
	val validParameterBox = parameterBox.tokens(0)._1 == InterestParamaterBoxNft

	
	val isValidDummyRegisters = (
		successor.R6[Boolean].get &&
		successor.R7[Boolean].get &&
		successor.R8[Boolean].get &&
		successor.R9[Boolean].get
	)


	sigmaProp(
		isReadyToUpdate &&
		validSuccessorScript &&
		retainedERG &&
		preservedInterestNFT &&
		validValueUpdate &&
		validFinalHeight &&
		validPoolBox &&
		validParameterBox &&
		isValidDummyRegisters
	)
}}''')