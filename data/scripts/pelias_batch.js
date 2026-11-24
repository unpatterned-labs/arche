// Read a JSON array of address strings on stdin; write, per address, pelias-parser's
// best solution as [{label, value, start, end}].
const P = process.env.PELIAS_PARSER
const AddressParser = require(P + '/parser/AddressParser')
const Tokenizer = require(P + '/tokenization/Tokenizer')
const parser = new AddressParser()
let raw = ''
process.stdin.on('data', d => { raw += d })
process.stdin.on('end', () => {
  const out = JSON.parse(raw).map(text => {
    const t = new Tokenizer(text)
    parser.classify(t)
    parser.solve(t)
    const best = t.solution[0]
    return best ? best.pair.map(c => ({ label: c.classification.label, value: c.span.body,
      start: c.span.start, end: c.span.end })) : []
  })
  process.stdout.write(JSON.stringify(out))
})
