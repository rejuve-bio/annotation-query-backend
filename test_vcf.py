import pysam
import sys

def validate_vcf_with_pysam(vcf_path):
    print(f"Checking {vcf_path}...")
    
    try:
        # 1. Attempt to open the file
        # This checks if the header is correctly formatted and matches VCF specs.
        vcf = pysam.VariantFile(vcf_path)
        
        # 2. Iterate through every record
        # This forces pysam to parse every line. If a line has missing columns
        # or bad data types (e.g., text in a Float field), it will crash here.
        count = 0
        for record in vcf:
            # Accessing attributes triggers the internal parsing validation
            _ = record.chrom
            _ = record.pos
            _ = record.id
            _ = record.alleles
            count += 1
            
        print(f"✅ SUCCESS: File is valid! Read {count} variants successfully.")
        return True

    except ValueError as e:
        # This catches formatting errors (like spaces instead of tabs)
        print(f"❌ INVALID VCF FORMAT: {e}")
        return False
    except OSError as e:
        # This catches file access errors or severe truncation
        print(f"❌ FILE ERROR: {e}")
        return False
    except Exception as e:
        # Catches other parsing issues
        print(f"❌ UNEXPECTED ERROR: {e}")
        return False

# Usage
# validate_vcf_with_pysam("/mnt/hdd_1/annotation-query-backend/public/vcf/694e7dc3f184a84edea03760.vcf")