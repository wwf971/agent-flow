const RANK_WIDTH = 12
const RANK_PATTERN = /^[0-9A-Za-z]{12}$/

export function isLexoRankValid(value: unknown) {
  return typeof value === 'string' && value.length === RANK_WIDTH && RANK_PATTERN.test(value)
}

export function sortByGlobalRank<T extends { rankGlobal?: string }>(itemList: T[]) {
  return itemList
    .map((item, index) => ({ item, index }))
    .sort((left, right) => {
      const isLeftRankValid = isLexoRankValid(left.item.rankGlobal)
      const isRightRankValid = isLexoRankValid(right.item.rankGlobal)
      if (isLeftRankValid !== isRightRankValid) return isLeftRankValid ? -1 : 1
      if (isLeftRankValid && isRightRankValid) {
        const leftRank = String(left.item.rankGlobal)
        const rightRank = String(right.item.rankGlobal)
        if (leftRank < rightRank) return -1
        if (leftRank > rightRank) return 1
      }
      return left.index - right.index
    })
    .map(({ item }) => item)
}
