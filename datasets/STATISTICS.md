# Dataset Statistics

Generated from the YAML source files in `name_equivalences/`.

## Summary

| Metric | Count |
|---|---|
| Total equivalence groups | 114 |
| Total variant entries in YAML | 340 |
| Unique non-canonical variants | 339 |
| Total name forms (canonical + variants) | 454 |
| Source files | 6 |
| Ethnic/linguistic traditions covered | 20+ |
| African regions covered | 5 (West, East, North, Southern, Cross-continental) |

Note: One variant entry (`Adekunle` in `west_african.yaml`) duplicates its canonical form, hence 340 variant entries but 339 unique non-canonical variants.

## Breakdown by Source File

| File | Tradition | Groups | Variants | Total Names |
|---|---|---|---|---|
| `pan_islamic.yaml` | Pan-Islamic / Arabic-origin | 19 | 121 | 140 |
| `west_african.yaml` | Yoruba, Igbo, Hausa, Fulani, Akan, Wolof | 44 | 105 | 149 |
| `east_african.yaml` | Swahili, Luo, Amharic, Tigrinya, Somali | 21 | 42 | 63 |
| `southern_african.yaml` | Zulu, Xhosa, Tswana, Sotho | 14 | 21 | 35 |
| `north_african.yaml` | Amazigh/Berber, Congolese, Malagasy | 8 | 14 | 22 |
| `cross_linguistic.yaml` | Colonial-era adaptations | 8 | 37 | 45 |
| **Total** | | **114** | **340** | **454** |

## Top 10 Largest Equivalence Groups

| Rank | Canonical | Tradition | Variants | Total Names |
|---|---|---|---|---|
| 1 | Mohammed | Pan-Islamic | 13 | 14 |
| 2 | Abdullahi | Pan-Islamic | 9 | 10 |
| 3 | Fatima | Pan-Islamic | 9 | 10 |
| 4 | Aisha | Pan-Islamic | 9 | 10 |
| 5 | Yusuf | Pan-Islamic | 8 | 9 |
| 6 | Ibrahim | Pan-Islamic | 7 | 8 |
| 7 | Suleiman | Pan-Islamic | 7 | 8 |
| 8 | Khadija | Pan-Islamic | 7 | 8 |
| 9 | Jean | Cross-linguistic | 6 | 7 |
| 10 | Usman | Pan-Islamic | 6 | 7 |

## Group Size Distribution

| Variants per Group | Number of Groups | Percentage |
|---|---|---|
| 1 variant | 12 | 10.5% |
| 2 variants | 41 | 36.0% |
| 3 variants | 18 | 15.8% |
| 4 variants | 13 | 11.4% |
| 5 variants | 9 | 7.9% |
| 6 variants | 7 | 6.1% |
| 7+ variants | 14 | 12.3% |

## Ethnic/Linguistic Sub-tradition Coverage

### West African (44 groups)

| Sub-tradition | Approximate Groups | Key Examples |
|---|---|---|
| Yoruba | 10 | Adeyemi, Babatunde, Oluwaseun, Temitope, Olayinka |
| Igbo | 9 | Chukwu, Okafor, Nnamdi, Chimamanda, Ugochukwu |
| Fulani / Pulaar | 6 | Diallo, Ba, Sow, Coulibaly, Traore |
| Akan / Ghanaian | 6 | Kwame, Kofi, Ama, Akua, Yaa, Adjoa |
| Hausa | 5 | Buhari, Sanusi, Abubakar, Binta, Hauwa |
| Wolof | 4 | Ndiaye, Fall, Gueye, Diop |
| Mandinka | 2 | Kone, Musa |

### East African (21 groups)

| Sub-tradition | Approximate Groups | Key Examples |
|---|---|---|
| Luo | 5 | Ochieng, Onyango, Akinyi, Odhiambo, Owuor |
| Amharic / Ethiopian | 4 | Abebe, Getachew, Haile, Tekle |
| Tigrinya | 4 | Berhe, Tesfaye, Gebremedhin, Abrehet |
| Swahili | 4 | Juma, Baraka, Mwalimu, Rehema |
| Somali | 2 | Abdi, Aden |
| Kikuyu | 2 | Mwangi, Kamau |

### Pan-Islamic (19 groups)

All 19 groups represent Arabic-origin names with wide regional adaptation:
Mohammed, Abdullahi, Ibrahim, Fatima, Aisha, Usman, Yusuf, Ali, Hassan, Hussein, Amina, Maryam, Ismail, Suleiman, Khadija, Zainab, Safiya, Halima, Ruqayya.

### Southern African (14 groups)

| Sub-tradition | Approximate Groups | Key Examples |
|---|---|---|
| Zulu / Xhosa | 6 | Dlamini, Ndlovu, Sipho, Nomusa, Nkomo, Thandiwe |
| Tswana / Sotho | 5 | Modise, Mokone, Thabo, Lerato, Mpho |
| Kikuyu (cross-listed) | 2 | Mwangi, Kamau |
| General | 1 | Mandela |

### North African & Other (8 groups)

| Sub-tradition | Groups | Key Examples |
|---|---|---|
| Amazigh / Berber + Arabic | 3 | Bouchta, Driss, Rachid |
| Congolese / Lingala | 3 | Kabila, Mukendi, Tshisekedi |
| Malagasy | 2 | Rakoto, Andrianaivo |

### Cross-linguistic / Colonial-era (8 groups)

Maps colonial-era name adaptations across Francophone, Anglophone, and Lusophone traditions:
Pierre/Peter/Petros, Jean/John/Yohana, Marie/Mary/Mariya, Joseph/Yusuf/Jose, Paul/Paulo/Bulus, David/Dauda/Dawud, James/Jacques/Yakubu, Elizabeth/Elisabeth/Erizabeti.

## Data Quality Notes

- All YAML files parse without errors
- Every group has at least 1 canonical name and 1 variant
- Diacritical marks are preserved in source (e.g., Yoruba subdots, French accents, Arabic transliterations)
- The SDK's `names.py` contains a hardcoded mirror of all 114 groups for offline use when YAML files are unavailable
- The bundled starter set (20 most-impactful groups) ships with the Apache 2.0 licensed SDK package

## Countries with Naming Traditions Represented

Nigeria, Senegal, Gambia, Guinea, Mali, Burkina Faso, Niger, Ghana, Sierra Leone, Liberia, Kenya, Uganda, Tanzania, Ethiopia, Eritrea, Somalia, South Africa, Botswana, Lesotho, Eswatini, DRC, Morocco, Algeria, Tunisia, Madagascar.
