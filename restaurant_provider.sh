#!/bin/sh

provider_get_restaurants_by_food() {
  provider_name=$1
  food_name=$2
  location=$3

  case $provider_name in
    mock)
      jq --arg term "$food_name" --arg location "$location" '
        def classification($category; $food):
          if $category == "한식" then
            {
              category: "한식",
              subcategory:
                (if ($food | test("탕|국|찌개")) then "국물/탕류"
                 elif ($food | test("삼겹살|불고기")) then "구이/고기류"
                 else "밥/정식류" end)
            }
          elif $category == "중식" then
            {
              category: "중식",
              subcategory:
                (if ($food | test("짜장면|짬뽕")) then "면/밥류"
                 elif ($food | test("만두")) then "만두/딤섬류"
                 elif ($food | test("마라")) then "마라/훠궈류"
                 else "고기류" end)
            }
          elif $category == "일식" then
            {
              category: "일식",
              subcategory:
                (if ($food | test("초밥|회")) then "초밥/회류"
                 elif ($food | test("라멘|우동")) then "면류"
                 elif ($food | test("돈가스|돈까스|가츠|톤카츠")) then "튀김/돈카츠류"
                 else "정식류" end)
            }
          elif $category == "분식" then
            {
              category: "분식",
              subcategory:
                (if ($food | test("떡볶이")) then "떡볶이류"
                 elif ($food | test("라면")) then "라면/국수류"
                 elif ($food | test("만두")) then "만두류"
                 else "튀김류" end)
            }
          elif $category == "세계음식" and ($food | test("쌀국수")) then
            {category: "베트남식", subcategory: "면/국물류"}
          elif $category == "세계음식" and ($food | test("양꼬치")) then
            {category: "중동/터키식", subcategory: "케밥/구이류"}
          elif $category == "양식" and ($food | test("버거")) then
            {category: "미국식", subcategory: "버거/샌드위치류"}
          elif $category == "양식" and ($food | test("스테이크")) then
            {category: "미국식", subcategory: "스테이크/바비큐류"}
          elif $category == "양식" and ($food | test("피자")) then
            {category: "양식/이탈리안", subcategory: "피자류"}
          else
            {category: "양식/이탈리안", subcategory: "파스타/리조또류"}
          end;
        map(
          . as $restaurant
          | classification(.category; .food) as $class
          | . + $class
          |
          select(
            (.food == $term)
            or (.category == $term)
            or (.subcategory == $term)
            or ((.name // "") | contains($term))
          )
          | . + {
              matched_terms: ([.matched_terms[]?] + [$term] | unique),
              address: (.address // .location // $location),
              roadAddress: (.roadAddress // .address // .location // $location),
              link: (.link // "")
            }
        )
      ' "$SCRIPT_DIR/dataset/mock_restaurants.json"
      ;;
    naver)
      naver_get_restaurants_by_food "$food_name" "$location" |
        jq --slurpfile menu "$SCRIPT_DIR/dataset/menu_categories.json" --arg term "$food_name" '
          def selected_main:
            [
              $menu[0]
              | to_entries[]
              | select(.value | index($term))
              | .key
            ][0] // "";
          map(
            . + {
              subcategory: (
                if selected_main != "" then $term else (.subcategory // "") end
              ),
              category: (
                if selected_main != "" then selected_main else .category end
              )
            }
          )
        '
      ;;
    *)
      printf '%s\n' "Unknown provider: $provider_name (use naver)" >&2
      return 1
      ;;
  esac
}
