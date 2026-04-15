## Domain: Pension / Insurance

### Terminology
- Policy/Scheme = Insurance policy or pension scheme
- Member/Annuitant = Person covered by the policy
- Beneficiary = Person who receives benefits
- Contingent = Backup/conditional beneficiary
- secondary beneficiary = 1st contingent beneficiary (SAME hierarchical position)
- tertiary beneficiary = 2nd contingent beneficiary (SAME hierarchical position)
- primary beneficiary ≠ contingent beneficiary (DIFFERENT positions)

### Disambiguation rules
- **Form of Annuity** in a reference/template refers to the *active election* the participant has chosen. When the input has both a "historical" column (e.g. "Original Form of Annuity at Commencement") and an "active/future" column (e.g. "Form of Annuity to Be Purchased"), the ACTIVE one is the correct match. The historical one goes in non_matches.
- **Uniform reference columns** (all rows identical, e.g. a single date or placeholder value) are template defaults, not real data. Do NOT match any input column to a uniform reference column — put the input in unmatched_input instead.
