/** Enzyme catalogue browser (searchable reference table). */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { Spinner } from '@/components/Ui'

export default function Enzymes() {
  const [search, setSearch] = useState('')
  const [commonOnly, setCommonOnly] = useState(false)
  const [overhang, setOverhang] = useState('')
  const catalogue = useQuery({ queryKey: ['enzymes'], queryFn: () => api.enzymes() })

  const rows = useMemo(() => {
    let list = catalogue.data?.enzymes ?? []
    if (commonOnly) list = list.filter((e) => e.common)
    if (overhang) list = list.filter((e) => e.overhang === overhang)
    if (search) {
      const needle = search.toLowerCase()
      list = list.filter((e) => e.name.toLowerCase().includes(needle) || e.site.toLowerCase().includes(needle))
    }
    return list
  }, [catalogue.data, search, commonOnly, overhang])

  return (
    <>
      <div className="topbar">
        <h1>Enzyme catalogue</h1>
        <span className="tag">{catalogue.data?.total_catalogue ?? 0} enzymes</span>
        <span className="spacer" />
        <input placeholder="Name or site (e.g. GAATTC)…" value={search} onChange={(e) => setSearch(e.target.value)} style={{ width: 240 }} />
        <select value={overhang} onChange={(e) => setOverhang(e.target.value)} style={{ width: 150 }}>
          <option value="">any overhang</option>
          <option value="5'">5′ overhang</option>
          <option value="3'">3′ overhang</option>
          <option value="blunt">blunt</option>
        </select>
        <label className="inline">
          <input type="checkbox" checked={commonOnly} onChange={(e) => setCommonOnly(e.target.checked)} /> common set
        </label>
      </div>
      <div className="content">
        {catalogue.isLoading && <Spinner />}
        <div className="card">
          <div className="body">
            <p className="tiny dim" style={{ marginTop: 0 }}>
              Cut positions use REBASE conventions: <span className="mono">G^AATT_C</span> marks the top (^) and bottom (_)
              strand cuts; Type IIS enzymes show the downstream offsets as <span className="mono">(n/m)</span>.
            </p>
            <table>
              <thead>
                <tr>
                  <th>Enzyme</th>
                  <th>Recognition</th>
                  <th>Overhang</th>
                  <th className="num">Length</th>
                  <th>Flags</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => (
                  <tr key={e.name}>
                    <td>
                      <b>{e.name}</b>
                    </td>
                    <td className="mono">{e.display_site}</td>
                    <td>
                      {e.overhang} {e.overhang_length > 0 && <span className="dim tiny">({e.overhang_length} nt)</span>}
                    </td>
                    <td className="num">{e.site.length}</td>
                    <td>
                      {e.common && <span className="tag ok">common</span>}{' '}
                      {e.type_iis && <span className="tag info">Type IIS</span>}{' '}
                      {e.palindromic ? '' : <span className="tag">non-palindromic</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  )
}
