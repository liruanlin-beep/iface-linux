# Changelog

## 3.0.1

This version packages the English Linux terminal edition with a numbered menu,
command-line interface and public Python API.

### Workflows

- Prepare optimization, surface, static, PDOS and charge-analysis inputs.
- Select exact potential variants and validate inputs before submission.
- Build periodic linear NEB paths and finite-difference vibrational inputs.
- Inspect energies, forces, barriers and harmonic prefactors with explicit checks.
- Generate fixed-geometry ENCUT and k-point sweeps.
- Convert ordered structures, generate slabs and search geometric interface candidates.
- Submit and cancel Slurm/PBS jobs only after explicit confirmation; preserve a
  durable record to prevent duplicate submissions.

### Validation fixes

- Reject invalid chemical element symbols in POSCAR input.
- Fall back to OSZICAR energy when OUTCAR provides no parsed energy.
- Finalize complete force tables at end of file.
- Reject incomplete or inconsistent final force tables and leave their maximum
  force unknown instead of retaining an earlier value.
- Check atom-wise active coordinates and mode counts before computing a harmonic
  prefactor from two vibrational calculations.

### Documentation

- Add standalone installation, API and contribution guides.
- Provide geometry examples that run without VASP or a scheduler.
- Document the executed offline checks and remaining validation limits in
  [VALIDATION.md](VALIDATION.md).

This changelog records the contents of the release; it does not claim earlier
public releases or completed live-cluster validation.
