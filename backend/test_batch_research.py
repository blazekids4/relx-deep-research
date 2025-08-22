from batch_research import main as batch_main
from batch_research import read_questions

def test_main():
    """Test version that only processes the first two questions."""
    # Read all questions but take only first two
    questions = read_questions("data/Sample Questions - Deep Research.csv")[:2]
    
    print("Test run with first two questions:")
    print(f"1. {questions[0]}")
    print(f"2. {questions[1]}")
    print("\nStarting processing...\n")
    
    # Override the read_questions function to return only our test questions
    def mock_read_questions(_):
        return questions
    
    # Replace the original read_questions in the batch_research module
    import batch_research
    batch_research.read_questions = mock_read_questions
    
    # Run the main function with our modified read_questions
    batch_main()

if __name__ == "__main__":
    test_main()
