package com.xianyu.cameraquality.model

import kotlin.math.hypot

object FocalLengthMath {
    private const val FULL_FRAME_DIAGONAL_MM = 43.266615305567875

    fun equivalent35mm(
        focalLengthMm: Double,
        sensorWidthMm: Double,
        sensorHeightMm: Double,
    ): Double? {
        if (focalLengthMm <= 0.0 || sensorWidthMm <= 0.0 || sensorHeightMm <= 0.0) {
            return null
        }

        val sensorDiagonal = hypot(sensorWidthMm, sensorHeightMm)
        return focalLengthMm * FULL_FRAME_DIAGONAL_MM / sensorDiagonal
    }

    fun distanceFromTarget(equivalentFocalLengths: List<Double>, targetMm: Double): Double =
        equivalentFocalLengths.minOfOrNull { kotlin.math.abs(it - targetMm) }
            ?: Double.POSITIVE_INFINITY
}
