```scala
{
    // CURRENT PLAN IS TO OFFER ONE STRIKE WITH 2 TIMES.
    // When a time is deleted a new one can be added (+ 1 month on the current)
    // Maintain 2d array of volumes
	
	// Constants
    val MaxLPTokens = 9000000000001000L
	val optionUnitSize = 10000000L // 0.01 ERGS
    val MinimumBoxValue = 1000000
    val LendTokenMultiplier = 1000000000000000L.toBigInt
    val OptionAddress = fromBase58("ELRnm8pk3r1FLmSTU5bt2JXpqM9unEdF1MjWAxTi7jeK")
    val MinTxFee = 1000000L
    val S = (1000000000000000L.toBigInt * CONTEXT.dataInputs(0).tokens(2)._2.toBigInt) / CONTEXT.dataInputs(0).value.toBigInt // Spot Price of 1000000 ERG
    val σ = CONTEXT.dataInputs(1).R9[Long].get
    val p = 1000000L.toBigInt // p is our precision
    val sqrtP = 1000L.toBigInt // Pre-computed sqrt(P)
    val CDF_NFT = fromBase58("5S4m2iXPzA7tGfxPHcATPXBYcTXc6LQ1jGj3H1buqydV") // Verification for CDF dataInput
    val MinutesInAYear = 262800L
	
	// User Defined Functions
	/**
	 * Calculates the natural logarithm of x using a Taylor series expansion.
	 * 
	 * This function approximates ln(x) using a Taylor series expansion. The series used is:
	 * ln(1 + x) ≈ x - x^2/2 + x^3/3 - x^4/4 + x^5/5 - x^6/6
	 * This expansion is adjusted by dividing each term by p (precision) to maintain appropriate scaling.
	 * 
	 * @param x The value for which the natural logarithm is being approximated multiplied by p.
	 * @return An approximation of ln(x) using the Taylor series expansion.
	 */
	def lnX(x: BigInt): BigInt = {
		(
			x -
			(x * x) / (2 * p) +
			(x * x * x) / (3 * p * p) - 
			(x * x * x * x) / (4 * p * p * p) + 
			(x * x * x * x * x) / (5 * p * p * p * p) - 
			(x * x * x * x * x * x) / (6 * p * p * p * p * p)
		)
	}

	/**
	 * Calculates the exponential of -x (e^-x) using a Taylor series expansion.
	 * 
	 * This function approximates e^-x using a Taylor series expansion. The series used is:
	 * e^-x ≈ 1 - x + x^2/2 - x^3/6 + x^4/24
	 * This expansion is adjusted by dividing each term by p (precision) to maintain appropriate scaling.
	 * 
	 * @param x The value for which the exponential function is being approximated.
	 * @return An approximation of e^-x using the Taylor series expansion.
	 */
	def eX(x: BigInt): BigInt = {
		(
			p -
			x +
			(x * x) / (2 * p) -
			(x * x * x) / (6 * p * p) +
			(x * x * x * x) / (24 * p * p * p)
		)
	}

	/**
	 * Checks if the second value is the square root of the first value within an acceptable error range.
	 * 
	 * This function takes a tuple containing two BigInt values: the original value and the supposed square root value.
	 * It calculates the square of the supposed square root and compares it to the original value.
	 * The function returns true if the calculated value is approximately equal to the original value, within an error range 2n+1 (given perfect squares are 2n+1 apart)
	 */
	def isValidSquareRoot(values: (BigInt, BigInt), p: BigInt): Boolean = {
	  val originalValue = values._1
	  val supposedSquareRoot = values._2
	  val calculatedValue = (supposedSquareRoot * supposedSquareRoot) / p
	  val error = (originalValue - calculatedValue)
	  val errorMargin = max(error, -1 * error)
	  
	  // Adaptive error margin based on the supposed square root
	  val adaptiveMargin = 2 * supposedSquareRoot + 1
	  errorMargin < adaptiveMargin
	}





    // Calculates d1 in Black-Scholes model
    def getD1(values: Coll[BigInt]) = {
        // Logic to calculate ln(S/K)
        val K = values(0)
        val y = values(1)
        val sqrtT = values(2)
        val t = values(3)
        val r = values(4)
        val x = y - p // Input in Taylor expansion
        val lnSK = lnX(x) * 8 // Multiply by 8 for equivalence to ln(S/K)
        // Calculate d1 by decomposing fraction into smaller parts
        (
            (p * p * lnSK) / (σ * sqrtT) +
            (p * t * r) / (σ * sqrtT) +
            (σ * t) / (2 * sqrtT)
        )
    }
    
	/**
	 * Validates that the second value is the correct triple square root of the first value within an acceptable error range.
	 * 
	 * This function takes a tuple containing two BigInt values: the original value and the supposed triple square root value.
	 * It calculates the ratio S/K and compares it to the calculated value using the supposed triple square root.
	 * The function returns true if the calculated value is approximately equal to the original value, within a dynamically determined error range.
	 */
	def isValidTripleSquareRoot(values: (BigInt, BigInt)): Boolean = {
		val strikePrice = values._1
		val supposedTripleSqrt = values._2
		val calculatedRatio = (S * p / strikePrice) // Calculates S / K 
		val calculatedValue = (supposedTripleSqrt * supposedTripleSqrt * supposedTripleSqrt * supposedTripleSqrt * 
							   supposedTripleSqrt * supposedTripleSqrt * supposedTripleSqrt * supposedTripleSqrt) / 
							  (p * p * p * p * p * p * p) 
		val errorMargin = calculatedRatio - calculatedValue
		val generalRatio = if (S > strikePrice )S / strikePrice else strikePrice / S
		errorMargin >= -12 * generalRatio && errorMargin <= 12 * generalRatio // Dynamic margin of accepted error, validates y hint
	}
	
    // Current state variables
    val currentScript = SELF.propositionBytes
    val currentPoolValue = SELF.value
    val currentPoolNft = SELF.tokens(0)
    val currentLPTokens = SELF.tokens(1)
    val currentYTokens = SELF.tokens(2)
    val currentCallTokens = SELF.tokens(3)
	val currentPutTokens = SELF.tokens(4)
    val currentRiskFreeRate = SELF.R4[Long].get
    val currentStrikes = SELF.R5[Coll[Long]].get // (Expiry, Strike, Amount)

    // Successor state variables
    val successor = OUTPUTS(0)
    val successorScript = successor.propositionBytes
    val successorPoolValue = successor.value
    val successorPoolNft = successor.tokens(0)
    val successorLPTokens = successor.tokens(1)
    val successorYTokens = successor.tokens(2)
    val successorCallTokens = successor.tokens(3)
	val successorPutTokens = successor.tokens(4)
    val successorRiskFreeRate = successor.R4[Long].get
    val successorStrikes = successor.R5[Coll[Long]].get // (Expiry, Strike)

    val currentLPCirculating = MaxLPTokens - currentLPTokens._2
    val currentXAmount = currentPoolValue
    val currentYAmount = currentYTokens._2

    val successorLPCirculating = MaxLPTokens - successorLPTokens._2
    val successorXAmount = successorPoolValue
    val successorYAmount = successorYTokens._2

    // Validation checks
    val isValidSuccessorScript = successorScript == currentScript
    val isPoolNftPreserved = successorPoolNft == currentPoolNft 
    val isValidLPTokenId = successorLPTokens._1 == currentLPTokens._1
    val isValidMinValue = successorPoolValue >= MinimumBoxValue 
    val isYIdPreserved = successorYTokens._1 == currentYTokens._1
    val isRiskFreeRateMaintained = successorRiskFreeRate == currentRiskFreeRate
    val isCallOptionIdRetained = successorCallTokens._1 == currentCallTokens._1
	val isPutOptionIdRetained = successorPutTokens._1 == currentPutTokens._1
    
    val commonReplication = (
        isValidSuccessorScript &&
        isPoolNftPreserved &&
        isValidLPTokenId &&
        isValidMinValue &&
        isYIdPreserved &&
        isRiskFreeRateMaintained &&
		isCallOptionIdRetained
    )
    
    sigmaProp(if (CONTEXT.dataInputs.size <= 2) {        
		val isLPMaintained = successorLPTokens == currentLPTokens
		val isXIncreasing = successorPoolValue - currentPoolValue > 0 // Assume all deposits offer at least some value to prevent spam
		val isYIncreasing = successorYAmount - currentYAmount >= 0
		val isInput0Self = INPUTS(0).id == SELF.id
		val isInput1Valid = INPUTS(1).tokens(0)._1 == currentCallTokens._1
		val isOptionTokensAmountValid = successorCallTokens._2 == currentCallTokens._2 + 1
		// OR PUT TOKENS

		// Validate deposit operation
		val isValidDeposit = (
			commonReplication &&
			isLPMaintained &&
			isXIncreasing &&
			isYIncreasing &&
			isInput0Self &&
			isInput1Valid &&
			isOptionTokensAmountValid
		)
		isValidDeposit      
    } else {
		val hints = successor.R6[Coll[Long]].get // (curr_height, y, sqrtT)
        val indices = successor.R7[Coll[Int]].get // (CDFIndex1, CDFIndex2)
		        
        val y = hints(1).toBigInt // Hint value for calculating the triple sqrt of a/b
		val yp = hints(2).toBigInt
        val sqrtT = hints(3).toBigInt // Hint value for sqrt(t)
        val CDFIndex1 = indices(0) // Asserted Index for Call N(d1)
        val CDFIndex2 = indices(1) // Asserted Index for Call N(d2)
		val CDFPutIndex1 = indices(2) // Asserted Index for Put N(d1)
        val CDFPutIndex2 = indices(3) // Asserted Index for Put N(d2)
        val CDF_Hint = CONTEXT.dataInputs(2) // CDF dataInput
        val CDF_keys = CDF_Hint.R4[Coll[Long]].get
        val CDF_values = CDF_Hint.R5[Coll[Long]].get
        val isValidCDF = CDF_Hint.tokens(0)._1 == CDF_NFT
				
		
		def getCallPrice(values: (BigInt, BigInt)) = {
			val t = values(0)
			val K = values(1)
			
			val r = currentRiskFreeRate
			
			val d1 = getD1(Coll(K.toBigInt, y, sqrtT, t, r.toBigInt))
			val d2 = d1 - ((σ * sqrtT) / p)
			
			val abs_d1 = max(d1, -1 * d1)
			val abs_d2 = max(d2, -1 * d2)
						
			val isCDFIndex1Valid = (
				((abs_d1 >= ((35 * p) / 10).toBigInt)  && (CDFIndex1 == CDF_keys.size - 1)) ||
				((CDF_keys(CDFIndex1).toBigInt <= abs_d1) && (CDF_keys(CDFIndex1 + 1).toBigInt >= abs_d1))
			)
			
			val isCDFIndex2Valid = (
				((abs_d2 >= ((35 * p) / 10).toBigInt)  && (CDFIndex2 == CDF_keys.size - 1)) ||
				((CDF_keys(CDFIndex2).toBigInt <= abs_d2) && (CDF_keys(CDFIndex2 + 1).toBigInt >= abs_d2))
			)
			
			val Nd1 = if (d1 >= 0) CDF_values(CDFIndex1).toBigInt else p - CDF_values(CDFIndex1).toBigInt
			val Nd2 = if (d2 >= 0) CDF_values(CDFIndex2).toBigInt else p - CDF_values(CDFIndex2).toBigInt
			
			val rt = (r * t) / p
			val ert = eX(rt)
				
			(((Nd1 * S) - (Nd2 * K * ert) / p), isCDFIndex1Valid && isCDFIndex2Valid)
		}
		
		
		def getPutPrice(values: (BigInt, BigInt)) = {
			val t = values(0)
			val K = values(1)
			
			val r = currentRiskFreeRate
			
			val d1 = getD1(Coll(K.toBigInt, yp, sqrtT, t, r.toBigInt))
			val d2 = d1 - ((σ * sqrtT) / p)
			
			val abs_d1 = max(d1, -1 * d1)
			val abs_d2 = max(d2, -1 * d2)
						
			val isCDFIndex1Valid = (
				((abs_d1 >= ((35 * p) / 10).toBigInt)  && (CDFPutIndex1 == CDF_keys.size - 1)) ||
				((CDF_keys(CDFPutIndex1).toBigInt <= abs_d1) && (CDF_keys(CDFPutIndex1 + 1).toBigInt >= abs_d1))
			)
			
			val isCDFIndex2Valid = (
				((abs_d2 >= ((35 * p) / 10).toBigInt)  && (CDFPutIndex2 == CDF_keys.size - 1)) ||
				((CDF_keys(CDFPutIndex2).toBigInt <= abs_d2) && (CDF_keys(CDFPutIndex2 + 1).toBigInt >= abs_d2))
			)
			
			val Nd1 = if (d1 >= 0) p - CDF_values(CDFPutIndex1).toBigInt else CDF_values(CDFPutIndex1).toBigInt
			val Nd2 = if (d2 >= 0) p - CDF_values(CDFPutIndex2).toBigInt else CDF_values(CDFPutIndex2).toBigInt
			
			val rt = (r * t) / p
			val ert = eX(rt)
				
			((((Nd2 * K * ert) / p) - (Nd1 * S)), isCDFIndex1Valid && isCDFIndex2Valid)
		}


		val isOptionTokensRetained = successorCallTokens == currentCallTokens
		val isPutTokensRetained = successorPutTokens == currentPutTokens
		if (isOptionTokensRetained && isPutTokensRetained) {
			// Exchange Path
			// Attempt to calculate total value of options outstanding
			val t_height = currentStrikes(0).toBigInt
			val K = currentStrikes(1).toBigInt
			val Kp = currentStrikes(3).toBigInt
		
			val retainStrikes = successorStrikes == currentStrikes

			val curr_height_hint = hints(0)
			val isValidHeightHint = HEIGHT >= curr_height_hint  && curr_height_hint < HEIGHT + 8
			val t = (t_height - curr_height_hint) * p / MinutesInAYear
			
			val callPriceResponse = getCallPrice((t, K))
			val putPriceResponse = getPutPrice((t, Kp))
			val callPrice = callPriceResponse(0)
			val putPrice = putPriceResponse(0)
			val isValidCDFIndices = callPriceResponse(1) && putPriceResponse(1)
			
			val xDeduction = putPrice * currentStrikes(4) / 100000000L.toBigInt
			val yDeduction = (callPrice * currentStrikes(2) * optionUnitSize) / 100000000L.toBigInt
			val xAddition = currentStrikes(2) * optionUnitSize
			val yAddition = currentStrikes(4)
			
			val currentTotalX = currentXAmount - xDeduction + xAddition
			val successorTotalX = successorXAmount - xDeduction + xAddition
			val currentTotalY = currentYAmount - yDeduction + yAddition
			val successorTotalY = successorYAmount - yDeduction +yAddition
			
			val currentXValue = LendTokenMultiplier * (currentTotalX.toBigInt) / currentLPCirculating.toBigInt
			val successorXValue = LendTokenMultiplier * (successorTotalX.toBigInt) / successorLPCirculating.toBigInt
			
			val currentYValue = LendTokenMultiplier * (currentTotalY.toBigInt) / currentLPCirculating.toBigInt
			val successorYValue = LendTokenMultiplier * (successorTotalY.toBigInt) / successorLPCirculating.toBigInt
			
			val isXValueMaintained = successorXValue > currentXValue // Ensures the current value of an LP token has not decreased
			val isYValueMaintained = successorYValue > currentYValue			
			
			val isValidExchange = (
				commonReplication &&
				isOptionTokensRetained &&
				isXValueMaintained &&
				isYValueMaintained &&
				retainStrikes &&
				isValidCDFIndices &&
				isValidCDF &&
				isValidHeightHint &&
				isValidSquareRoot((t, sqrtT)) &&
				isValidTripleSquareRoot((K, y)) &&
				isValidTripleSquareRoot((Kp, yp))
			)
			isValidExchange
	
		} else if (isPutTokensRetained) {
			// Trade Path
			val isLPMaintained = successorLPTokens == currentLPTokens
			val deltaYTokens = successorYAmount - currentYAmount
			val isSellingOption = deltaYTokens < 0
			val optionBox = if (isSellingOption) INPUTS(1) else OUTPUTS(1)
			val optionScript = optionBox.propositionBytes
			val optionValue = optionBox.value
			val K = optionBox.R4[Long].get.toBigInt // Strike Price
			val t_height = optionBox.R5[Long].get // Expiry Block
			val strike_indices = optionBox.R7[Coll[Int]].get // (ExpiryIndex, StrikeIndex)
			val expiry_index = strike_indices(0)
			val strike_index = strike_indices(1)
			val callsOutstanding = if (isSellingOption) currentStrikes(2).toBigInt * optionUnitSize.toBigInt else successorStrikes(2).toBigInt * optionUnitSize.toBigInt
			val xAmountToUse = if (isSellingOption) currentXAmount else successorXAmount
			val callUtility = p + p * (callsOutstanding) / (xAmountToUse + callsOutstanding)
			
			val isValidIndices = (
				currentStrikes(expiry_index) == t_height &&
				currentStrikes(strike_index) == K
			) || isSellingOption
		
			val optionSizeNErgs = if (isSellingOption) (successorPoolValue - currentPoolValue) else (currentPoolValue - successorPoolValue) 
			val isValidOptionSize = optionSizeNErgs % optionUnitSize == 0
			val optionSize = optionSizeNErgs / optionUnitSize
			
			
			val currentStrikeCount = currentStrikes(strike_index + 1) // Implement correct logic for this
			val successorStrikeCount = successorStrikes(strike_index + 1) // Implement correct logic for this
			val correctStrikeAdjustment = if (isSellingOption) {
				currentStrikeCount - optionSize == successorStrikeCount
			} else {
				currentStrikeCount + optionSize == successorStrikeCount
			}
				
			val curr_height_hint = hints(0)
			
			val isValidHeightHint = HEIGHT >= curr_height_hint  && curr_height_hint < HEIGHT + 8
			val t = (t_height - curr_height_hint) * p / MinutesInAYear
			
			val isValidOptionScript = blake2b256(optionScript) == OptionAddress
			
			val isValidOptionValue = optionValue >= optionSize + MinTxFee
			val isValidOptionBox = (
				optionBox.tokens(0)._1 == currentCallTokens._1 &&
				optionBox.tokens(0)._2 == 1
			)
			
			val callPriceResponse = getCallPrice((t, K))
			val callPrice = callPriceResponse(0)
			val isValidCDFIndices = callPriceResponse(1)
			
			val isValidPrice = if (isSellingOption) {
				-1 * deltaYTokens <= callPrice.toBigInt * optionSize.toBigInt / (callUtility * 100000000L.toBigInt)
			} else {
				deltaYTokens >= callUtility * callPrice.toBigInt * optionSize.toBigInt / (p * p * 100000000L.toBigInt)
			}
			val isYTokenIdRetained = successorYTokens._1 == currentYTokens._1
			
			val isValidTrade = (
				commonReplication &&
				isValidOptionBox &&
				isValidOptionScript && 
				isValidOptionValue &&
				isValidOptionSize &&
				isValidCDF &&
				isValidPrice &&
				isValidHeightHint &&
				isValidCDFIndices &&
				correctStrikeAdjustment &&
				isValidSquareRoot((t, sqrtT)) &&
				isValidTripleSquareRoot((K, y))
			)
			isValidTrade
		} else {
			// Trade Path
			val isLPMaintained = successorLPTokens == currentLPTokens
			val deltaXTokens = successorXAmount - currentXAmount
			val isSellingOption = deltaXTokens < 0
			val optionBox = if (isSellingOption) INPUTS(1) else OUTPUTS(1)
			val optionScript = optionBox.propositionBytes
			val optionValue = optionBox.value
			val optionYTokens = optionBox.tokens(1)
			val K = optionBox.R4[Long].get.toBigInt // Strike Price
			val t_height = optionBox.R5[Long].get // Expiry Block
			val strike_indices = optionBox.R7[Coll[Int]].get // (ExpiryIndex, StrikeIndex)
			val expiry_index = strike_indices(0)
			val strike_index = strike_indices(1)
			val putsOutstanding = if (isSellingOption) currentStrikes(4).toBigInt  else successorStrikes(4).toBigInt 
			val yAmountToUse = if (isSellingOption) currentYAmount else successorYAmount
			val putUtility = p + p * (putsOutstanding) / (yAmountToUse + putsOutstanding)
			
			val isValidIndices = (
				currentStrikes(expiry_index) == t_height &&
				currentStrikes(strike_index) == K
			) || isSellingOption
		
			val optionSize = if (isSellingOption) (successorYAmount - currentYAmount) else (currentYAmount - successorYAmount) 			
			
			val currentStrikeCount = currentStrikes(strike_index + 1) // Implement correct logic for this
			val successorStrikeCount = successorStrikes(strike_index + 1) // Implement correct logic for this
			val correctStrikeAdjustment = if (isSellingOption) {
				currentStrikeCount - optionSize == successorStrikeCount
			} else {
				currentStrikeCount + optionSize == successorStrikeCount
			}
				
			val curr_height_hint = hints(0)
			
			val isValidHeightHint = HEIGHT >= curr_height_hint  && curr_height_hint < HEIGHT + 8
			val t = (t_height - curr_height_hint) * p / MinutesInAYear
			
			val isValidOptionScript = blake2b256(optionScript) == OptionAddress
			
			val isValidOptionValue = optionValue >= 2 * MinTxFee
			val isValidOptionBox = (
				optionBox.tokens(0)._1 == currentPutTokens._1 &&
				optionBox.tokens(0)._2 == 1
			)
			val isValidYTokens = (
				optionBox.tokens(1)._1 == currentYTokens._1 &&
				optionBox.tokens(1)._2 == optionSize
			)
			
			val putPriceResponse = getPutPrice((t, K))
			val putPrice = putPriceResponse(0)
			val isValidCDFIndices = putPriceResponse(1)
			
			val isValidPrice = if (isSellingOption) {
				-1 * deltaXTokens <= p * putPrice.toBigInt * optionSize.toBigInt / (putUtility * p * 100000000L.toBigInt)
			} else {
				deltaXTokens >= putUtility * putPrice.toBigInt * optionSize.toBigInt / (p * p * 100000000L.toBigInt)
			}
			val isYTokenIdRetained = successorYTokens._1 == currentYTokens._1
			
			val isValidTrade = (
				commonReplication &&
				isValidOptionBox &&
				isValidOptionScript && 
				isValidOptionValue &&
				isValidYTokens &&
				isValidCDF &&
				isValidPrice &&
				isValidHeightHint &&
				isValidCDFIndices &&
				correctStrikeAdjustment &&
				isValidSquareRoot((t, sqrtT)) &&
				isValidTripleSquareRoot((K, y))
			)
			isValidTrade		
		}
    })
}
```
