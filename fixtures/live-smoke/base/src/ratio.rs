pub fn ratio(numerator: i64, denominator: i64) -> Option<i64> {
    if denominator == 0 {
        return None;
    }
    Some(numerator / denominator)
}
